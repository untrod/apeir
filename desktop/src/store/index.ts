/**
 * Nous Store — Unified entity management.
 *
 * Usage:
 *   import { entityStore, eventClient, useConversations, useTasks, ... } from "./store";
 */

export { entityStore } from "./entityStore";
export { eventClient } from "./eventClient";
export {
  useConversations, useConversation,
  useSessions, useActiveSession,
  useMessages,
  useTasks, useTask, useActiveTasks,
  usePlans, usePlan,
  useApprovals, usePendingApprovals, useApproval,
  useArtifacts, useArtifact,
  useVerifications, useVerification,
  useNodes, useNode, useOnlineNodes, usePrimaryNode,
  useModels, useModel,
  useEvidence,
  useUsage, useCostSummary,
  useWorkspace,
  useStoreHydrated, useEventCursor,
} from "./hooks";
export type {
  EntityId, Timestamp, SequenceNumber,
  Conversation, Session, Message, MessageRole,
  Task, TaskStatus, TaskStep,
  Plan, PlanStage,
  Approval, ApprovalAction,
  Artifact, ArtifactKind,
  Verification, VerificationEvidence,
  Node, NodeRole, NodeCapability,
  Model, ModelProviderKind, ModelProbe, ModelCalibration,
  Evidence,
  UsageRecord, CostSummary,
  WorkspaceEntry, WorkspaceFile,
  RuntimeEventEnvelope,
  EntityStoreState,
} from "./types";
