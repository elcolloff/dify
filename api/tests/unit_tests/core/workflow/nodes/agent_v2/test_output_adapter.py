from agenton.compositor import CompositorSessionSnapshot
from unittest.mock import patch

from clients.agent_backend import (
    AgentBackendRunCancelledInternalEvent,
    AgentBackendRunFailedInternalEvent,
    AgentBackendRunPausedInternalEvent,
    AgentBackendRunSucceededInternalEvent,
)
from core.workflow.file_reference import build_file_reference
from core.workflow.nodes.agent_v2.output_adapter import WorkflowAgentOutputAdapter
from graphon.enums import WorkflowNodeExecutionMetadataKey, WorkflowNodeExecutionStatus
from graphon.file import File, FileTransferMethod, FileType
from graphon.variables.segments import ArrayFileSegment, FileSegment
from models.agent_config_entities import DeclaredArrayItem, DeclaredOutputConfig, DeclaredOutputType


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


def test_success_output_adapter_preserves_dict_output():
    result = WorkflowAgentOutputAdapter().build_success_result(
        event=AgentBackendRunSucceededInternalEvent(
            run_id="run-1",
            source_event_id="2-0",
            output={"summary": "ok"},
            session_snapshot=CompositorSessionSnapshot(layers=[]),
        ),
        inputs={},
        process_data={},
        metadata={"agent_backend": {"run_id": "run-1"}},
    )

    assert result.status == WorkflowNodeExecutionStatus.SUCCEEDED
    assert result.outputs == {"summary": "ok"}
    assert result.metadata[WorkflowNodeExecutionMetadataKey.AGENT_LOG]["agent_backend"]["status"] == "succeeded"
    assert result.metadata[WorkflowNodeExecutionMetadataKey.AGENT_LOG]["agent_backend"]["session_snapshot"] == {
        "layer_count": 0,
    }


def test_failure_output_adapter_maps_paused_to_unsupported_failure():
    result = WorkflowAgentOutputAdapter().build_failure_result(
        event=AgentBackendRunPausedInternalEvent(
            run_id="run-1",
            source_event_id="2-0",
            reason="human",
            message=None,
            session_snapshot=None,
        ),
        inputs={},
        process_data={},
        metadata={},
    )

    assert result.status == WorkflowNodeExecutionStatus.FAILED
    assert result.error_type == "agent_backend_paused_unsupported"


def test_failure_output_adapter_preserves_backend_failed_reason():
    result = WorkflowAgentOutputAdapter().build_failure_result(
        event=AgentBackendRunFailedInternalEvent(
            run_id="run-1",
            source_event_id="2-0",
            error="bad request",
            reason="validation",
        ),
        inputs={},
        process_data={},
        metadata={},
    )

    assert result.status == WorkflowNodeExecutionStatus.FAILED
    assert result.error == "bad request"
    assert result.error_type == "validation"


def test_success_output_adapter_normalizes_string_and_scalar_outputs():
    adapter = WorkflowAgentOutputAdapter()
    string_result = adapter.build_success_result(
        event=AgentBackendRunSucceededInternalEvent(
            run_id="run-1",
            source_event_id="2-0",
            output="hello",
            session_snapshot=CompositorSessionSnapshot(layers=[]),
        ),
        inputs={},
        process_data={},
        metadata={},
    )
    scalar_result = adapter.build_success_result(
        event=AgentBackendRunSucceededInternalEvent(
            run_id="run-2",
            source_event_id="2-0",
            output=3,
            session_snapshot=CompositorSessionSnapshot(layers=[]),
        ),
        inputs={},
        process_data={},
        metadata={},
    )

    assert string_result.outputs == {"text": "hello"}
    assert scalar_result.outputs == {"result": 3}


def test_success_output_adapter_normalizes_file_output_to_file_segments():
    upload_reference = build_file_reference(record_id="upload-file-1")
    tool_reference = build_file_reference(record_id="tool-file-1")
    with patch(
        "core.workflow.nodes.agent_v2.output_adapter.build_from_mapping",
        side_effect=[
            _restored_file(transfer_method=FileTransferMethod.LOCAL_FILE, reference=upload_reference),
            _restored_file(transfer_method=FileTransferMethod.TOOL_FILE, reference=tool_reference),
        ],
    ):
        result = WorkflowAgentOutputAdapter().build_success_result(
            event=AgentBackendRunSucceededInternalEvent(
                run_id="run-1",
                source_event_id="2-0",
                output={
                    "report": {
                        "transfer_method": "local_file",
                        "reference": upload_reference,
                    },
                    "attachments": [
                        {
                            "transfer_method": "tool_file",
                            "reference": tool_reference,
                        }
                    ],
                },
                session_snapshot=CompositorSessionSnapshot(layers=[]),
            ),
            inputs={},
            process_data={},
            metadata={"tenant_id": "tenant-1"},
            declared_outputs=[
                DeclaredOutputConfig(name="report", type=DeclaredOutputType.FILE),
                DeclaredOutputConfig(
                    name="attachments",
                    type=DeclaredOutputType.ARRAY,
                    array_item=DeclaredArrayItem(type=DeclaredOutputType.FILE),
                ),
            ],
        )

    report = result.outputs["report"]
    assert isinstance(report, FileSegment)
    assert report.value.transfer_method == FileTransferMethod.LOCAL_FILE
    assert report.value.reference == upload_reference

    attachments = result.outputs["attachments"]
    assert isinstance(attachments, ArrayFileSegment)
    assert attachments.value[0].transfer_method == FileTransferMethod.TOOL_FILE
    assert attachments.value[0].reference == tool_reference


def test_success_output_adapter_accepts_canonical_file_mapping_for_declared_file_output():
    tool_reference = build_file_reference(record_id="tool-file-1")
    with patch(
        "core.workflow.nodes.agent_v2.output_adapter.build_from_mapping",
        return_value=_restored_file(transfer_method=FileTransferMethod.TOOL_FILE, reference=tool_reference),
    ):
        result = WorkflowAgentOutputAdapter().build_success_result(
            event=AgentBackendRunSucceededInternalEvent(
                run_id="run-1",
                source_event_id="2-0",
                output={"report": {"transfer_method": "tool_file", "reference": tool_reference}},
                session_snapshot=CompositorSessionSnapshot(layers=[]),
            ),
            inputs={},
            process_data={},
            metadata={"tenant_id": "tenant-1"},
            declared_outputs=[DeclaredOutputConfig(name="report", type=DeclaredOutputType.FILE)],
        )

    report = result.outputs["report"]
    assert isinstance(report, FileSegment)
    assert report.value.transfer_method == FileTransferMethod.TOOL_FILE
    assert report.value.reference == tool_reference


def test_success_output_adapter_accepts_canonical_datasource_file_mapping_for_declared_file_output():
    datasource_reference = build_file_reference(record_id="datasource-file-1")
    with patch(
        "core.workflow.nodes.agent_v2.output_adapter.build_from_mapping",
        return_value=_restored_file(
            transfer_method=FileTransferMethod.DATASOURCE_FILE,
            reference=datasource_reference,
        ),
    ):
        result = WorkflowAgentOutputAdapter().build_success_result(
            event=AgentBackendRunSucceededInternalEvent(
                run_id="run-1",
                source_event_id="2-0",
                output={"report": {"transfer_method": "datasource_file", "reference": datasource_reference}},
                session_snapshot=CompositorSessionSnapshot(layers=[]),
            ),
            inputs={},
            process_data={},
            metadata={"tenant_id": "tenant-1"},
            declared_outputs=[DeclaredOutputConfig(name="report", type=DeclaredOutputType.FILE)],
        )

    report = result.outputs["report"]
    assert isinstance(report, FileSegment)
    assert report.value.transfer_method == FileTransferMethod.DATASOURCE_FILE
    assert report.value.reference == datasource_reference


def test_success_output_adapter_accepts_canonical_remote_url_mapping_for_declared_file_output():
    remote_url = "https://example.com/report.pdf"

    result = WorkflowAgentOutputAdapter().build_success_result(
        event=AgentBackendRunSucceededInternalEvent(
            run_id="run-1",
            source_event_id="2-0",
            output={"report": {"transfer_method": "remote_url", "url": remote_url}},
            session_snapshot=CompositorSessionSnapshot(layers=[]),
        ),
        inputs={},
        process_data={},
        metadata={"tenant_id": "tenant-1"},
        declared_outputs=[DeclaredOutputConfig(name="report", type=DeclaredOutputType.FILE)],
    )

    report = result.outputs["report"]
    assert isinstance(report, FileSegment)
    assert report.value.transfer_method == FileTransferMethod.REMOTE_URL
    assert report.value.remote_url == remote_url


def test_success_output_adapter_accepts_canonical_file_mapping_for_declared_array_file_output():
    tool_reference = build_file_reference(record_id="tool-file-1")
    with patch(
        "core.workflow.nodes.agent_v2.output_adapter.build_from_mapping",
        return_value=_restored_file(transfer_method=FileTransferMethod.TOOL_FILE, reference=tool_reference),
    ):
        result = WorkflowAgentOutputAdapter().build_success_result(
            event=AgentBackendRunSucceededInternalEvent(
                run_id="run-1",
                source_event_id="2-0",
                output={"attachments": [{"transfer_method": "tool_file", "reference": tool_reference}]},
                session_snapshot=CompositorSessionSnapshot(layers=[]),
            ),
            inputs={},
            process_data={},
            metadata={"tenant_id": "tenant-1"},
            declared_outputs=[
                DeclaredOutputConfig(
                    name="attachments",
                    type=DeclaredOutputType.ARRAY,
                    array_item=DeclaredArrayItem(type=DeclaredOutputType.FILE),
                )
            ],
        )

    attachments = result.outputs["attachments"]
    assert isinstance(attachments, ArrayFileSegment)
    assert attachments.value[0].transfer_method == FileTransferMethod.TOOL_FILE
    assert attachments.value[0].reference == tool_reference


def test_success_output_adapter_does_not_treat_generic_object_with_string_id_as_file():
    result = WorkflowAgentOutputAdapter().build_success_result(
        event=AgentBackendRunSucceededInternalEvent(
            run_id="run-1",
            source_event_id="2-0",
            output={"meta": {"id": "123", "type": "summary"}},
            session_snapshot=CompositorSessionSnapshot(layers=[]),
        ),
        inputs={},
        process_data={},
        metadata={},
    )

    assert result.outputs["meta"] == {"id": "123", "type": "summary"}


def test_success_output_adapter_does_not_crash_on_generic_object_with_non_string_id():
    result = WorkflowAgentOutputAdapter().build_success_result(
        event=AgentBackendRunSucceededInternalEvent(
            run_id="run-1",
            source_event_id="2-0",
            output={"meta": {"id": 1, "name": "foo"}},
            session_snapshot=CompositorSessionSnapshot(layers=[]),
        ),
        inputs={},
        process_data={},
        metadata={},
    )

    assert result.outputs["meta"] == {"id": 1, "name": "foo"}


def test_success_output_adapter_preserves_nested_canonical_file_mapping_inside_object_output():
    tool_reference = build_file_reference(record_id="tool-file-1")
    result = WorkflowAgentOutputAdapter().build_success_result(
        event=AgentBackendRunSucceededInternalEvent(
            run_id="run-1",
            source_event_id="2-0",
            output={
                "meta": {
                    "attachment": {
                        "transfer_method": "tool_file",
                        "reference": tool_reference,
                    }
                }
            },
            session_snapshot=CompositorSessionSnapshot(layers=[]),
        ),
        inputs={},
        process_data={},
        metadata={},
        declared_outputs=[DeclaredOutputConfig(name="meta", type=DeclaredOutputType.OBJECT)],
    )

    assert result.outputs["meta"] == {
        "attachment": {
            "transfer_method": "tool_file",
            "reference": tool_reference,
        }
    }


def test_success_output_adapter_preserves_nested_canonical_file_mapping_inside_generic_array_output():
    tool_reference = build_file_reference(record_id="tool-file-1")
    result = WorkflowAgentOutputAdapter().build_success_result(
        event=AgentBackendRunSucceededInternalEvent(
            run_id="run-1",
            source_event_id="2-0",
            output={
                "items": [
                    {
                        "attachment": {
                            "transfer_method": "tool_file",
                            "reference": tool_reference,
                        }
                    }
                ]
            },
            session_snapshot=CompositorSessionSnapshot(layers=[]),
        ),
        inputs={},
        process_data={},
        metadata={},
        declared_outputs=[
            DeclaredOutputConfig(
                name="items",
                type=DeclaredOutputType.ARRAY,
                array_item=DeclaredArrayItem(type=DeclaredOutputType.OBJECT),
            )
        ],
    )

    assert result.outputs["items"] == [
        {
            "attachment": {
                "transfer_method": "tool_file",
                "reference": tool_reference,
            }
        }
    ]


def test_success_output_adapter_does_not_normalize_top_level_canonical_file_mapping_without_declared_file_field():
    tool_reference = build_file_reference(record_id="tool-file-1")
    result = WorkflowAgentOutputAdapter().build_success_result(
        event=AgentBackendRunSucceededInternalEvent(
            run_id="run-1",
            source_event_id="2-0",
            output={
                "transfer_method": "tool_file",
                "reference": tool_reference,
            },
            session_snapshot=CompositorSessionSnapshot(layers=[]),
        ),
        inputs={},
        process_data={},
        metadata={"tenant_id": "tenant-1"},
        declared_outputs=[DeclaredOutputConfig(name="text", type=DeclaredOutputType.STRING, required=False)],
    )

    assert result.outputs == {
        "transfer_method": "tool_file",
        "reference": tool_reference,
    }


def test_success_output_adapter_maps_backend_usage_to_llm_usage_and_metadata():
    result = WorkflowAgentOutputAdapter().build_success_result(
        event=AgentBackendRunSucceededInternalEvent(
            run_id="run-1",
            source_event_id="2-0",
            output={"summary": "ok"},
            session_snapshot=CompositorSessionSnapshot(layers=[]),
        ),
        inputs={},
        process_data={},
        metadata={
            "agent_backend": {
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                }
            }
        },
    )

    assert result.llm_usage.prompt_tokens == 10
    assert result.llm_usage.completion_tokens == 5
    assert result.llm_usage.total_tokens == 15
    assert result.metadata[WorkflowNodeExecutionMetadataKey.TOTAL_TOKENS] == 15


def test_failure_output_adapter_maps_cancelled_to_failure_code():
    result = WorkflowAgentOutputAdapter().build_failure_result(
        event=AgentBackendRunCancelledInternalEvent(
            run_id="run-1",
            source_event_id="2-0",
            reason="user_cancelled",
            message=None,
        ),
        inputs={},
        process_data={},
        metadata={},
    )

    assert result.status == WorkflowNodeExecutionStatus.FAILED
    assert result.error_type == "agent_backend_run_cancelled"


def test_stream_exhausted_result_is_failed_with_stream_error():
    result = WorkflowAgentOutputAdapter().build_stream_exhausted_result(
        inputs={},
        process_data={},
        metadata={"agent_backend": {"run_id": "run-1"}},
    )

    assert result.status == WorkflowNodeExecutionStatus.FAILED
    assert result.error_type == "agent_backend_stream_error"
    assert result.metadata[WorkflowNodeExecutionMetadataKey.AGENT_LOG]["agent_backend"]["run_id"] == "run-1"
