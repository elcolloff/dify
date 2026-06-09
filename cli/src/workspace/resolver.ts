import type { ActiveContext } from '@/auth/hosts'
import { BaseError } from '@/errors/base'
import { ErrorCode } from '@/errors/codes'

export type WorkspaceResolveInputs = {
  readonly flag?: string
  readonly env?: string
  readonly active?: ActiveContext
}

export function resolveWorkspaceId(inputs: WorkspaceResolveInputs): string {
  if (truthy(inputs.flag))
    return inputs.flag
  if (truthy(inputs.env))
    return inputs.env
  const wsId = inputs.active?.ctx.workspace?.id
  if (truthy(wsId))
    return wsId
  throw new BaseError({
    code: ErrorCode.UsageMissingArg,
    message: 'no workspace selected',
    hint: 'pass --workspace, set DIFY_WORKSPACE_ID, or run \'difyctl use workspace <id>\'',
  })
}

function truthy(v: string | undefined): v is string {
  return v !== undefined && v !== ''
}
