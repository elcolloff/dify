from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from clients.agent_backend import (
    AgentBackendRunEventAdapter,
    AgentBackendStreamInternalEvent,
    FakeAgentBackendRunClient,
    FakeAgentBackendScenario,
)
from dify_agent.protocol import RunStartedEvent, RunSucceededEvent, RunSucceededEventData
from core.app.entities.app_invoke_entities import DIFY_RUN_CONTEXT_KEY, DifyRunContext, InvokeFrom, UserFrom
from core.workflow.file_reference import build_file_reference
from core.workflow.nodes.agent_v2 import DifyAgentNode
from core.workflow.nodes.agent_v2.binding_resolver import WorkflowAgentBindingBundle, WorkflowAgentBindingResolver
from core.workflow.nodes.agent_v2.entities import DifyAgentNodeData
from core.workflow.nodes.agent_v2.output_adapter import WorkflowAgentOutputAdapter
from core.workflow.nodes.agent_v2.runtime_request_builder import WorkflowAgentRuntimeRequestBuilder
from graphon.entities import GraphInitParams
from graphon.enums import BuiltinNodeTypes, WorkflowNodeExecutionMetadataKey, WorkflowNodeExecutionStatus
from graphon.file import File, FileTransferMethod, FileType
from graphon.node_events import StreamCompletedEvent
from graphon.runtime import GraphRuntimeState
from graphon.variables.segments import ArrayFileSegment, FileSegment, StringSegment
from models.agent import Agent, AgentConfigSnapshot, WorkflowAgentNodeBinding
from models.agent_config_entities import (
    AgentSoulConfig,
    AgentSoulModelConfig,
    DeclaredOutputType,
    WorkflowNodeJobConfig,
)


class FakeCredentialsProvider:
    def fetch(self, provider_name: str, model_name: str) -> dict[str, object]:
        assert provider_name == "openai"
        assert model_name == "gpt-test"
        return {"api_key": "secret-key"}


def _restored_file(*, transfer_method: FileTransferMethod, reference: str) -> File:
    return File(
        type=FileType.DOCUMENT,
        transfer_method=transfer_method,
        remote_url=None,
        reference=reference,
        filename="report.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        size=12,
    )


class FakeVariablePool:
    def get(self, selector):
        values = {
            ("sys", "query"): "Summarize the report.",
            ("sys", "workflow_run_id"): "workflow-run-1",
            ("sys", "conversation_id"): "conversation-1",
            ("previous-node", "text"): "Previous result",
        }
        value = values.get(tuple(selector))
        if value is None:
            return None
        return StringSegment(value=value)

    def get_by_prefix(self, prefix):
        return {}


class FakeBindingResolver(WorkflowAgentBindingResolver):
    def __init__(self):
        self.agent = Agent(id="agent-1", tenant_id="tenant-1", name="Agent")
        self.snapshot = AgentConfigSnapshot(
            id="snapshot-1",
            tenant_id="tenant-1",
            agent_id="agent-1",
            version=1,
            config_snapshot=AgentSoulConfig(
                prompt={"system_prompt": "You are careful."},
                model=AgentSoulModelConfig(
                    plugin_id="langgenius/openai",
                    model_provider="openai",
                    model="gpt-test",
                ),
            ),
        )
        self.binding = WorkflowAgentNodeBinding(
            id="binding-1",
            tenant_id="tenant-1",
            app_id="app-1",
            workflow_id="workflow-1",
            node_id="agent-node",
            agent_id="agent-1",
            current_snapshot_id="snapshot-1",
            node_job_config=WorkflowNodeJobConfig.model_validate(
                {
                    "workflow_prompt": "Use the previous output.",
                    "previous_node_output_refs": [{"node_id": "previous-node", "output": "text"}],
                    "declared_outputs": [{"name": "text", "type": "string"}],
                }
            ),
        )

    def resolve(self, **_kwargs):
        return WorkflowAgentBindingBundle(binding=self.binding, agent=self.agent, snapshot=self.snapshot)


class FileOutputBackendClient(FakeAgentBackendRunClient):
    output_payload: dict[str, object]

    def __init__(self, *, output_payload: dict[str, object]) -> None:
        super().__init__(scenario=FakeAgentBackendScenario.SUCCESS)
        self.output_payload = output_payload

    def _events(self, run_id: str):
        from clients.agent_backend.fake_client import _FIXED_TIME
        from agenton.compositor import CompositorSessionSnapshot

        return (
            RunStartedEvent(id="1-0", run_id=run_id, created_at=_FIXED_TIME),
            RunSucceededEvent(
                id="2-0",
                run_id=run_id,
                created_at=_FIXED_TIME,
                data=RunSucceededEventData(
                    output=self.output_payload,
                    session_snapshot=CompositorSessionSnapshot(layers=[]),
                ),
            ),
        )


def _node(
    *,
    scenario: FakeAgentBackendScenario = FakeAgentBackendScenario.SUCCESS,
    declared_outputs: list[dict[str, object]] | None = None,
    agent_backend_client: FakeAgentBackendRunClient | None = None,
) -> DifyAgentNode:
    graph_init_params = GraphInitParams(
        workflow_id="workflow-1",
        graph_config={"nodes": [], "edges": []},
        run_context={
            DIFY_RUN_CONTEXT_KEY: DifyRunContext(
                tenant_id="tenant-1",
                app_id="app-1",
                user_id="user-1",
                user_from=UserFrom.ACCOUNT,
                invoke_from=InvokeFrom.DEBUGGER,
            )
        },
        call_depth=0,
    )
    from core.workflow.nodes.agent_v2.output_failure_orchestrator import OutputFailureOrchestrator
    from core.workflow.nodes.agent_v2.output_type_checker import PerOutputTypeChecker

    class _AlwaysAllowFileValidator:
        def is_accessible_file_mapping(self, *, file_id: str, tenant_id: str, transfer_method) -> bool:
            return True

    binding_resolver = FakeBindingResolver()
    if declared_outputs is not None:
        binding_resolver.binding.node_job_config = WorkflowNodeJobConfig.model_validate(
            {
                "workflow_prompt": "Use the previous output.",
                "previous_node_output_refs": [{"node_id": "previous-node", "output": "text"}],
                "declared_outputs": declared_outputs,
            }
        )

    return DifyAgentNode(
        node_id="agent-node",
        data=DifyAgentNodeData.model_validate({"type": BuiltinNodeTypes.AGENT, "version": "2"}),
        graph_init_params=graph_init_params,
        graph_runtime_state=cast(GraphRuntimeState, SimpleNamespace(variable_pool=FakeVariablePool())),
        binding_resolver=binding_resolver,
        runtime_request_builder=WorkflowAgentRuntimeRequestBuilder(credentials_provider=FakeCredentialsProvider()),
        agent_backend_client=agent_backend_client or FakeAgentBackendRunClient(scenario=scenario),
        event_adapter=AgentBackendRunEventAdapter(),
        output_adapter=WorkflowAgentOutputAdapter(),
        type_checker=PerOutputTypeChecker(file_validator=_AlwaysAllowFileValidator()),
        failure_orchestrator=OutputFailureOrchestrator(),
    )


def test_agent_node_run_maps_successful_agent_backend_run_to_node_result():
    events = list(_node()._run())

    assert len(events) == 1
    result = cast(StreamCompletedEvent, events[0]).node_run_result
    assert result.status == WorkflowNodeExecutionStatus.SUCCEEDED
    assert result.outputs == {"text": "hello agent"}
    agent_log = result.metadata[WorkflowNodeExecutionMetadataKey.AGENT_LOG]
    assert agent_log["agent_backend"]["run_id"] == "fake-run-1"
    assert agent_log["agent_backend"]["status"] == "succeeded"
    assert result.process_data["agent_id"] == "agent-1"
    assert result.inputs["agent_backend_request"]["composition"]["layers"][4]["config"]["credentials"] == "[REDACTED]"


def test_agent_node_run_normalizes_declared_file_output_with_canonical_mapping():
    tool_reference = build_file_reference(record_id="tool-file-1")
    with patch(
        "core.workflow.nodes.agent_v2.output_adapter.build_from_mapping",
        return_value=_restored_file(transfer_method=FileTransferMethod.TOOL_FILE, reference=tool_reference),
    ):
        events = list(
            _node(
                declared_outputs=[{"name": "report", "type": DeclaredOutputType.FILE}],
                agent_backend_client=FileOutputBackendClient(
                    output_payload={"report": {"transfer_method": "tool_file", "reference": tool_reference}}
                ),
            )._run()
        )

    result = cast(StreamCompletedEvent, events[0]).node_run_result
    report = result.outputs["report"]
    assert isinstance(report, FileSegment)
    assert report.value.reference == tool_reference


def test_agent_node_run_normalizes_declared_datasource_file_output_with_canonical_mapping():
    datasource_reference = build_file_reference(record_id="datasource-file-1")
    with patch(
        "core.workflow.nodes.agent_v2.output_adapter.build_from_mapping",
        return_value=_restored_file(
            transfer_method=FileTransferMethod.DATASOURCE_FILE,
            reference=datasource_reference,
        ),
    ):
        events = list(
            _node(
                declared_outputs=[{"name": "report", "type": DeclaredOutputType.FILE}],
                agent_backend_client=FileOutputBackendClient(
                    output_payload={"report": {"transfer_method": "datasource_file", "reference": datasource_reference}}
                ),
            )._run()
        )

    result = cast(StreamCompletedEvent, events[0]).node_run_result
    report = result.outputs["report"]
    assert isinstance(report, FileSegment)
    assert report.value.transfer_method == FileTransferMethod.DATASOURCE_FILE
    assert report.value.reference == datasource_reference


def test_agent_node_run_normalizes_declared_remote_url_file_output_with_canonical_mapping():
    remote_url = "https://example.com/report.pdf"

    events = list(
        _node(
            declared_outputs=[{"name": "report", "type": DeclaredOutputType.FILE}],
            agent_backend_client=FileOutputBackendClient(
                output_payload={"report": {"transfer_method": "remote_url", "url": remote_url}}
            ),
        )._run()
    )

    result = cast(StreamCompletedEvent, events[0]).node_run_result
    report = result.outputs["report"]
    assert isinstance(report, FileSegment)
    assert report.value.transfer_method == FileTransferMethod.REMOTE_URL
    assert report.value.remote_url == remote_url


def test_agent_node_run_normalizes_declared_array_file_output_with_canonical_mappings():
    first_reference = build_file_reference(record_id="tool-file-1")
    second_reference = build_file_reference(record_id="tool-file-2")
    with patch(
        "core.workflow.nodes.agent_v2.output_adapter.build_from_mapping",
        side_effect=[
            _restored_file(transfer_method=FileTransferMethod.TOOL_FILE, reference=first_reference),
            _restored_file(transfer_method=FileTransferMethod.TOOL_FILE, reference=second_reference),
        ],
    ):
        events = list(
            _node(
                declared_outputs=[
                    {
                        "name": "attachments",
                        "type": DeclaredOutputType.ARRAY,
                        "array_item": {"type": DeclaredOutputType.FILE},
                    }
                ],
                agent_backend_client=FileOutputBackendClient(
                    output_payload={
                        "attachments": [
                            {"transfer_method": "tool_file", "reference": first_reference},
                            {"transfer_method": "tool_file", "reference": second_reference},
                        ]
                    }
                ),
            )._run()
        )

    result = cast(StreamCompletedEvent, events[0]).node_run_result
    attachments = result.outputs["attachments"]
    assert isinstance(attachments, ArrayFileSegment)
    assert [item.reference for item in attachments.value] == [first_reference, second_reference]


def test_agent_node_run_maps_failed_agent_backend_run_to_node_result():
    events = list(_node(scenario=FakeAgentBackendScenario.FAILED)._run())

    assert len(events) == 1
    result = cast(StreamCompletedEvent, events[0]).node_run_result
    assert result.status == WorkflowNodeExecutionStatus.FAILED
    assert result.error == "fake failure"
    assert result.error_type == "unit_test"


def test_agent_node_records_stream_usage_metadata():
    metadata = {"agent_backend": {"run_id": "run-1"}}

    DifyAgentNode._record_stream_metadata(
        metadata,
        AgentBackendStreamInternalEvent(
            run_id="run-1",
            source_event_id="1-1",
            event_kind="model_response",
            data={"usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}},
        ),
    )

    agent_backend = metadata["agent_backend"]
    assert agent_backend["last_stream_event_id"] == "1-1"
    assert agent_backend["last_stream_event_kind"] == "model_response"
    assert agent_backend["usage"] == {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
