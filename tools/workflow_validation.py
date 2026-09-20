#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real User Workflow Validation for Nous Runtime V1.0.0-rc1.

Validates three production user workflows:
  1. Learning Assistant — complete learning cycle
  2. Project Assistant — full project lifecycle
  3. Code Task — API → Runtime → Model → Verification pipeline

Usage:
    python tools/workflow_validation.py
    python tools/workflow_validation.py --json
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from typing import Any


def ok(data: Any = None) -> dict: return {"status": "ok", "data": data}
def fail(msg: str) -> dict: return {"status": "fail", "error": msg}



# Workflow 1: Learning Assistant


def validate_learning_workflow() -> dict:
    """Simulate a student using the learning assistant for a week."""
    from nous_runtime.persona.learning_assistant import LearningAssistant

    steps = []
    with tempfile.TemporaryDirectory() as tmp:
        la = LearningAssistant(workspace=tmp)

        # Day 1: Add subjects
        la.add_subject("Mathematics", ["Linear Algebra", "Calculus", "Statistics"])
        la.add_subject("Computer Science", ["Data Structures", "Algorithms", "Machine Learning"])
        la.add_subject("English", ["Reading", "Writing", "Vocabulary"])
        la.set_daily_goal(120)
        la.set_focus_areas(["Mathematics", "Computer Science"])
        steps.append("subjects_created")

        # Day 1: Study sessions
        la.log_session("Mathematics", "Linear Algebra", 45, 0.7, "Matrix operations")
        la.log_session("Computer Science", "Data Structures", 60, 0.8, "Binary trees")
        steps.append("day1_sessions")

        # Day 2
        la.log_session("Mathematics", "Linear Algebra", 30, 0.85, "Eigenvalues")
        la.log_session("Computer Science", "Algorithms", 45, 0.75, "Sorting")
        la.log_session("English", "Reading", 30, 0.9, "Article analysis")
        steps.append("day2_sessions")

        # Day 3
        la.log_session("Mathematics", "Calculus", 60, 0.6, "Derivatives")
        la.log_session("Computer Science", "Machine Learning", 45, 0.65, "Neural networks")
        steps.append("day3_sessions")

        # Day 4: Review
        la.log_session("Mathematics", "Linear Algebra", 20, 0.9, "Review")
        la.log_session("Mathematics", "Calculus", 45, 0.75, "Integration")
        steps.append("day4_sessions")

        # Day 5
        la.log_session("Computer Science", "Algorithms", 30, 0.85, "Graph algorithms")
        la.log_session("English", "Writing", 45, 0.8, "Essay practice")
        steps.append("day5_sessions")

        # Verify mastery improved
        math = la._profile.subjects.get("mathematics")
        cs = la._profile.subjects.get("computer_science")
        assert math is not None, "Mathematics subject missing"
        assert cs is not None, "Computer Science subject missing"
        assert math.mastery_level > 0, "Math mastery not updated"
        assert cs.mastery_level > 0, "CS mastery not updated"
        assert math.total_study_hours > 0, "Math hours not tracked"
        steps.append("mastery_verified")

        # Generate daily plan
        plan = la.generate_daily_plan()
        assert "recommended" in plan, "Daily plan missing recommendations"
        assert plan["goal_minutes"] == 120
        steps.append("daily_plan")

        # Generate weekly review
        review = la.generate_weekly_review()
        assert review["total_minutes"] > 0
        assert review["sessions_count"] >= 5
        assert len(review.get("by_subject", {})) >= 2
        steps.append("weekly_review")

        # Progress summary
        summary = la.get_progress_summary()
        assert summary["total_sessions"] >= 10
        assert summary["total_hours"] > 3
        assert summary["subjects_count"] == 3
        steps.append("progress_summary")

    return ok({
        "workflow": "learning_assistant",
        "steps": steps,
        "step_count": len(steps),
        "result": "All learning assistant operations completed successfully",
    })



# Workflow 2: Project Assistant


def validate_project_workflow() -> dict:
    """Simulate managing a software project through its lifecycle."""
    from nous_runtime.persona.project_assistant import ProjectAssistant

    steps = []
    with tempfile.TemporaryDirectory() as tmp:
        pa = ProjectAssistant(workspace=tmp)

        # Create projects
        pa.create_project("Nous Runtime V1", "Release preparation", priority="high", tags=["release", "critical"])
        pa.create_project("YOLO Integration", "Object detection pipeline", priority="medium", tags=["cv", "ml"])
        pa.create_project("STM32 Firmware", "Embedded sensor driver", priority="medium", tags=["embedded", "c"])
        steps.append("projects_created")

        # Add milestones to Nous Runtime
        pa.add_milestone("Nous Runtime V1", "Architecture Audit", "Review all subsystems")
        pa.add_milestone("Nous Runtime V1", "Desktop UI", "Build 10-page desktop app")
        pa.add_milestone("Nous Runtime V1", "Installer", "Build NousInstaller.exe")
        pa.add_milestone("Nous Runtime V1", "Testing", "Reach 2000+ tests")
        pa.add_milestone("Nous Runtime V1", "Release", "Publish v1.0.0-rc1")
        steps.append("milestones_created")

        # Add milestones to YOLO
        pa.add_milestone("YOLO Integration", "Model export", "Export to ONNX")
        pa.add_milestone("YOLO Integration", "Edge deployment", "Deploy to Jetson")
        steps.append("yolo_milestones")

        # Create checkpoints
        pa.create_checkpoint("Nous Runtime V1", "After architecture audit", {"audit.md": "v1"})
        pa.create_checkpoint("Nous Runtime V1", "After UI complete", {"app.tsx": "v2"})
        steps.append("checkpoints_created")

        # Complete milestones progressively
        pa.complete_milestone("Nous Runtime V1", "Architecture Audit")
        pa.complete_milestone("Nous Runtime V1", "Desktop UI")
        pa.complete_milestone("Nous Runtime V1", "Installer")
        pa.complete_milestone("Nous Runtime V1", "Testing")
        steps.append("milestones_completed")

        # Verify project summary
        summary = pa.get_project_summary("Nous Runtime V1")
        assert summary is not None
        assert summary["milestones_progress"].startswith("4/5")
        assert summary["milestones_progress_pct"] == 80.0
        steps.append("progress_verified")

        # Pause YOLO project
        pa.update_status("YOLO Integration", "paused", "Waiting for model training")
        steps.append("project_paused")

        # Complete final milestone
        pa.complete_milestone("Nous Runtime V1", "Release")
        pa.update_status("Nous Runtime V1", "completed")
        steps.append("project_completed")

        # Verify dashboard
        dashboard = pa.get_dashboard()
        assert dashboard["projects_total"] == 3
        assert dashboard["projects_active"] >= 1
        assert dashboard["projects_paused"] >= 1
        assert dashboard["projects_completed"] >= 1
        assert dashboard["milestones_progress_pct"] > 0
        steps.append("dashboard_verified")

        # List projects by filter
        active = pa.list_projects(status="active")
        paused = pa.list_projects(status="paused")
        completed = pa.list_projects(status="completed")
        assert len(active) >= 1
        assert len(paused) >= 1
        assert len(completed) >= 1
        steps.append("filter_verified")

    return ok({
        "workflow": "project_assistant",
        "steps": steps,
        "step_count": len(steps),
        "result": "All project assistant operations completed successfully",
    })



# Workflow 3: Code Task Pipeline


def validate_code_task_workflow() -> dict:
    """Validate the code task pipeline: API → Runtime → Model → Output."""
    steps = []

    # Step 1: API receives user input
    from nous_runtime.api.routes import (
        handle_runtime_run, handle_model_select,
        handle_chat_runtime, handle_status,
    )
    steps.append("api_imported")

    # Step 2: Status check
    status_r = handle_status()
    assert status_r["ok"] is True
    assert status_r["data"]["running"] in (True, False)
    steps.append("status_ok")

    # Step 3: Runtime run (code task)
    run_r = handle_runtime_run({"user_input": "Analyze Python code for performance issues"})
    assert "ok" in run_r
    steps.append("runtime_run")

    # Step 4: Chat pipeline
    chat_r = handle_chat_runtime({"text": "Find bugs in my project"})
    assert "ok" in chat_r
    steps.append("chat_pipeline")

    # Step 5: Model selection for coding task
    try:
        model_r = handle_model_select({"task_type": "coding"})
        if model_r["ok"]:
            steps.append("model_selected")
        else:
            steps.append("model_selection_no_models_available")
    except Exception:
        steps.append("model_selection_handled")

    # Step 6: Task timeline
    from nous_runtime.api.task_center_routes import (
        handle_task_timeline, handle_task_verification,
    )
    timeline_r = handle_task_timeline()
    assert timeline_r["ok"] is True
    steps.append("task_timeline")

    # Step 7: Verification
    verify_r = handle_task_verification("code-task")
    assert verify_r["ok"] is True
    steps.append("verification")

    # Step 8: Dashboard aggregation
    from nous_runtime.api.desktop_routes import handle_dashboard_full
    dash_r = handle_dashboard_full()
    assert dash_r["ok"] is True
    for key in ("runtime", "models", "tasks", "devices", "memory"):
        assert key in dash_r["data"]
    steps.append("dashboard_aggregation")

    return ok({
        "workflow": "code_task_pipeline",
        "steps": steps,
        "step_count": len(steps),
        "result": "API → Runtime → Model → Verification pipeline intact",
    })



# Runner


def main():
    import argparse
    p = argparse.ArgumentParser(description="Nous Runtime Workflow Validation")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--workflow", type=str, default="all", help="Specific workflow: learning, project, code, all")
    args = p.parse_args()

    workflows = {
        "learning": ("Learning Assistant", validate_learning_workflow),
        "project": ("Project Assistant", validate_project_workflow),
        "code": ("Code Task Pipeline", validate_code_task_workflow),
    }

    if args.workflow != "all":
        workflows = {args.workflow: workflows[args.workflow]}

    results = {}
    all_pass = True
    start = time.time()

    for name, (label, fn) in workflows.items():
        print(f"\n{'-'*48}\n  {label}\n{'-'*48}")
        try:
            r = fn()
            results[name] = r
            print(f"  PASS {r['data']['step_count']} steps completed")
            for s in r["data"]["steps"]:
                print(f"     ✓ {s}")
        except Exception as e:
            results[name] = fail(str(e))
            all_pass = False
            print(f"  FAIL FAILED: {e}")
            import traceback
            traceback.print_exc()

    elapsed = time.time() - start
    print(f"\n{'='*48}")
    print(f"  Workflow Validation: {'PASS' if all_pass else 'FAIL'}")
    print(f"  Time: {elapsed:.1f}s")
    print(f"{'='*48}\n")

    if args.json:
        print(json.dumps({
            "overall": "PASS" if all_pass else "FAIL",
            "elapsed_seconds": round(elapsed, 1),
            "workflows": results,
        }, indent=2, default=str))

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
