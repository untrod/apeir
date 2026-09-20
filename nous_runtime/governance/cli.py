# -*- coding: utf-8 -*-
"""Governance CLI commands — nous approval, nous authorization, nous delegation."""

from __future__ import annotations

import json
import os
import getpass
import typer

from nous_runtime.governance import (
    ApprovalManager,
    AuthorizationContext,
    DelegationManager,
    LeaseManager,
    get_store,
)

approval_app = typer.Typer(help="Approval management")
authorization_app = typer.Typer(help="Authorization inspection")
delegation_app = typer.Typer(help="Delegation management")


def _subject_id() -> str:
    return f"{getpass.getuser()}@{os.environ.get('COMPUTERNAME', 'localhost')}"


def _build_context() -> AuthorizationContext:
    return AuthorizationContext(
        subject_type="user",
        subject_id=_subject_id(),
        authn_method="cli_os_user",
        authn_confidence=0.8,
        session_locality="local",
        session_device=os.environ.get("COMPUTERNAME", "localhost"),
    )


# Approval

@approval_app.command("list")
def approval_list(json_output: bool = typer.Option(False, "--json", help="Machine-readable output")):
    """List pending approval requests."""
    mgr = ApprovalManager()
    pending = mgr.get_pending(_subject_id())
    if json_output:
        typer.echo(json.dumps({"pending": pending, "count": len(pending)}, indent=2))
    else:
        if not pending:
            typer.echo("No pending approvals.")
            return
        typer.echo("PENDING APPROVALS")
        typer.echo(f"{'REQUEST ID':<14} {'ACTION':<28} {'PRIORITY':<10} {'EXPIRES':<20}")
        typer.echo("-" * 72)
        for r in pending:
            typer.echo(
                f"{r['request_id'][:12]:<14} "
                f"{r.get('summary', '?')[:26]:<28} "
                f"{r.get('priority', 'normal'):<10} "
                f"{r.get('expires_at', '?'):<20}"
            )
        typer.echo(f"\n{len(pending)} pending. Use 'nous approval show <id>' for details.")


@approval_app.command("show")
def approval_show(request_id: str = typer.Argument(..., help="Approval request ID"),
                  json_output: bool = typer.Option(False, "--json")):
    """Show details of an approval request."""
    mgr = ApprovalManager()
    req = mgr.get_request(request_id)
    if not req:
        typer.echo(f"Approval request '{request_id}' not found.", err=True)
        raise typer.Exit(code=1)

    if json_output:
        typer.echo(json.dumps(req, indent=2))
        return

    typer.echo("=" * 64)
    typer.echo("  APPROVAL REQUIRED")
    typer.echo("=" * 64)
    typer.echo(f"  Request ID:  {req['request_id']}")
    typer.echo(f"  Action:      {req.get('summary', '?')}")
    typer.echo(f"  Risk:        {req.get('risk_summary', '?')}")
    typer.echo(f"  Scope:       {req.get('scope_summary', '?')}")
    typer.echo(f"  Status:      {req.get('status', '?')}")
    typer.echo(f"  Requested:   {req.get('requested_at', '?')}")
    typer.echo(f"  Expires:     {req.get('expires_at', '?')}")
    typer.echo("=" * 64)
    typer.echo("  Type 'nous approval approve <id>' to approve.")
    typer.echo("  Type 'nous approval deny <id>' to reject.")


@approval_app.command("approve")
def approval_approve(request_id: str = typer.Argument(..., help="Approval request ID")):
    """Approve a pending approval request."""
    mgr = ApprovalManager()
    req = mgr.get_request(request_id)
    if not req:
        typer.echo(f"Approval request '{request_id}' not found.", err=True)
        raise typer.Exit(code=1)
    if req["status"] != "PENDING":
        typer.echo(f"Request is {req['status']}, not PENDING.", err=True)
        raise typer.Exit(code=1)

    response = mgr.approve(request_id, _subject_id())
    typer.echo(f"Approved. Response: {response.response_id}")


@approval_app.command("deny")
def approval_deny(request_id: str = typer.Argument(..., help="Approval request ID"),
                  reason: str = typer.Option("", "--reason", help="Reason for denial")):
    """Deny a pending approval request."""
    mgr = ApprovalManager()
    req = mgr.get_request(request_id)
    if not req:
        typer.echo(f"Approval request '{request_id}' not found.", err=True)
        raise typer.Exit(code=1)
    if req["status"] != "PENDING":
        typer.echo(f"Request is {req['status']}, not PENDING.", err=True)
        raise typer.Exit(code=1)

    response = mgr.deny(request_id, _subject_id(), reason=reason)
    typer.echo(f"Denied. Response: {response.response_id}")


@approval_app.command("revoke")
def approval_revoke(lease_id: str = typer.Argument(..., help="Lease ID to revoke"),
                    reason: str = typer.Option("", "--reason")):
    """Revoke an active authorization lease."""
    mgr = LeaseManager()
    try:
        revocation = mgr.revoke(lease_id, _subject_id(), reason=reason)
        typer.echo(f"Lease {lease_id} revoked. Revocation: {revocation.revocation_id}")
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1)


# Authorization

@authorization_app.command("show")
def authorization_show(decision_id: str = typer.Argument(..., help="Decision ID"),
                       json_output: bool = typer.Option(False, "--json")):
    """Show an authorization decision."""
    store = get_store()
    decision = store.get_decision(decision_id)
    if not decision:
        typer.echo(f"Decision '{decision_id}' not found.", err=True)
        raise typer.Exit(code=1)

    if json_output:
        typer.echo(json.dumps(decision, indent=2))
        return

    typer.echo(f"Authorization Decision: {decision['decision_id']}")
    typer.echo(f"  Action mode: {decision.get('action_mode', '?')}")
    typer.echo(f"  Allowed:     {decision.get('allowed', False)}")
    typer.echo(f"  Reason:      {decision.get('reason_code', '?')}: {decision.get('reason_message', '?')}")
    typer.echo(f"  Rule class:  {decision.get('rule_class', '?')}")
    typer.echo(f"  Lease:       {decision.get('lease_id', 'none')}")
    typer.echo(f"  Decided at:  {decision.get('decided_at', '?')}")


@authorization_app.command("leases")
def authorization_leases(json_output: bool = typer.Option(False, "--json")):
    """List active authorization leases."""
    mgr = LeaseManager()
    leases = mgr.list_active(_subject_id())
    if json_output:
        typer.echo(json.dumps({"leases": leases, "count": len(leases)}, indent=2))
    else:
        if not leases:
            typer.echo("No active leases.")
            return
        typer.echo("ACTIVE LEASES")
        typer.echo(f"{'LEASE ID':<14} {'PROPOSAL':<16} {'USES':<10} {'EXPIRES':<20}")
        typer.echo("-" * 60)
        for lease in leases:
            typer.echo(
                f"{lease['lease_id'][:12]:<14} "
                f"{lease.get('proposal_hash', '?')[:14]:<16} "
                f"{lease.get('remaining_uses', 0)}/{lease.get('max_uses', 0):<7} "
                f"{lease.get('expires_at', '?'):<20}"
            )


# Delegation

@delegation_app.command("list")
def delegation_list(json_output: bool = typer.Option(False, "--json")):
    """List active delegation grants."""
    mgr = DelegationManager()
    grants = mgr.list_active(_subject_id())
    if json_output:
        typer.echo(json.dumps({"delegations": grants, "count": len(grants)}, indent=2))
    else:
        if not grants:
            typer.echo("No active delegations.")
            return
        typer.echo("ACTIVE DELEGATIONS")
        typer.echo(f"{'GRANT ID':<14} {'ISSUER':<16} {'SUBJECT':<16} {'USES':<10} {'EXPIRES':<20}")
        typer.echo("-" * 76)
        for g in grants:
            typer.echo(
                f"{g['grant_id'][:12]:<14} "
                f"{g.get('issuer_id', '?')[:14]:<16} "
                f"{g.get('subject_id', '?')[:14]:<16} "
                f"{g.get('used_count', 0)}/{g.get('max_uses', 0):<7} "
                f"{g.get('expires_at', '?'):<20}"
            )


@delegation_app.command("revoke")
def delegation_revoke(grant_id: str = typer.Argument(..., help="Grant ID to revoke"),
                      reason: str = typer.Option("", "--reason")):
    """Revoke an active delegation grant."""
    mgr = DelegationManager()
    try:
        revocation = mgr.revoke(grant_id, _subject_id(), reason=reason)
        typer.echo(f"Delegation {grant_id} revoked. Revocation: {revocation.revocation_id}")
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1)
