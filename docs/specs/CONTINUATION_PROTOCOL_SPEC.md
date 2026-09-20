# Continuation Protocol Specification v1.0

> Status: Draft — Phase 0.5
> Defines "continue" semantics for long-running projects

---

## 1. Overview

The Continuation Protocol defines how a user (or scheduler) requests that a paused or interrupted project resume work. The key principle: **ambiguous continuation produces a plan, not arbitrary action.**

---

## 2. Continuation Request

### 2.1 Request Types

| Scope | Description |
|---|---|
| `any_pending` | Continue the next available WorkItem (most common) |
| `specific_work_item` | Continue a specific WorkItem by ID |
| `next_milestone` | Continue the next incomplete Milestone's first pending WorkItem |
| `retry_failed` | Retry the most recent failed WorkItem |

### 2.2 Resolution Algorithm

```
function resolve_continuation(project_id, scope):
    project = load_project(project_id)
    
    if project.status == "cancelled":
        return ResumeDecision(action="wait", reason="project cancelled")
    
    if project.status == "completed":
        return ResumeDecision(action="wait", reason="project completed")
    
    if scope == "specific_work_item":
        item = get_work_item(scope.work_item_id)
        if item.status in ["pending", "queued"]:
            return check_dependencies_and_execute(item)
        else:
            return ResumeDecision(action="wait", reason=f"item status is {item.status}")
    
    if scope == "retry_failed":
        failed_items = get_failed_work_items(project_id)
        if failed_items:
            return check_dependencies_and_execute(failed_items[0])
        else:
            return ResumeDecision(action="wait", reason="no failed items to retry")
    
    # any_pending or next_milestone
    candidates = get_pending_items_with_satisfied_dependencies(project_id)
    
    if scope == "next_milestone":
        candidates = filter_by_next_incomplete_milestone(candidates)
    
    if len(candidates) == 0:
        return ResumeDecision(action="wait", reason="no pending items with satisfied dependencies")
    
    if len(candidates) == 1:
        return ResumeDecision(action="execute", work_item=candidates[0])
    
    # Multiple candidates: ambiguity -> plan, not action
    plan = generate_work_plan(candidates)
    return ResumeDecision(action="plan", plan=plan, 
                         reason=f"{len(candidates)} candidates: producing plan for review")
```

---

## 3. Pause Protocol

### 3.1 PauseRequest

```json
{
  "pause_id": "pause_20260713_a1b2",
  "project_id": "proj_20260713_a1b2",
  "work_item_id": null,
  "reason": "Taking a break",
  "requested_at": "2026-07-13T18:00:00Z",
  "requested_by": "user"
}
```

### 3.2 Pause Behavior

| If work_item_id | Behavior |
|---|---|
| `null` (pause project) | Stop dispatching new WorkItems. Running items complete current step then pause. |
| Specific WorkItem | Pause only that WorkItem's ExecutionSession. Other items continue. |

### 3.3 Pause Is Not Cancel
- Paused items can be resumed
- Paused items preserve continuation_context
- Paused items do not release their workspace lease (unless pause exceeds lease TTL)

---

## 4. Resume After Crash

### 4.1 Crash Recovery Logic

```
function recover_after_restart():
    for each project:
        for each work_item with status "running":
            if work_item.is_idempotent:
                # Safe to re-submit
                re_submit_task(work_item)
            else:
                # Not safe to re-submit
                mark_failed(work_item, reason="crash_recovery")
                notify_user(f"Task {work_item.id} was interrupted. Please review and re-submit.")
        
        for each work_item with status "assigned":
            # Task was assigned but may or may not have been received
            # Re-deliver with idempotency key for dedup
            re_deliver_task(work_item)
        
        for each work_item with status "queued":
            # Safe — never left the queue
            pass  # Will be picked up when node reconnects
```

### 4.2 External Side Effects
External side effects (git pushes, API calls, file modifications) are NOT automatically resumed after crash. The user must explicitly re-submit non-idempotent tasks.

---

## 5. Watch Continuation

### 5.1 Allowed
- `scope: "any_pending"` — continue the next available work item
- Only for LOW risk tasks
- Requires the task was previously defined (not creating new tasks)

### 5.2 Prohibited
- HIGH/CRITICAL risk task continuation
- `scope: "specific_work_item"` (no browsing/selecting on watch)
- Creating new WorkItems
- Modifying WorkItem parameters

### 5.3 Confirmation
Watch continuation shows: project name, work item description, risk level. User confirms with single tap. No scope-detail display required (task was previously defined and reviewed).
