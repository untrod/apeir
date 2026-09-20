# Nous Runtime for VS Code

This MVP is a client of the authoritative Nous Server Runtime.

1. Start the Runtime on localhost.
2. Run `Nous: Configure Runtime Token`; the token is stored in VS Code SecretStorage. Submit an empty value to remove it.
3. Run `Nous: Open Runtime` for status, runs, providers and pending approvals.
4. Select editor text and use the `Nous` context-menu actions.
5. Use `Nous: Approve Request` or `Nous: Reject Request` with the displayed request ID. ApprovalBroker identity and self-approval prevention remain authoritative.
6. Use `Nous: Open Timeline` after reconnecting; read-only calls retry once and replay canonical Runtime data.

The extension stores no independent Run, Event, Conversation or Approval state. The default endpoint is `http://localhost:8770`; remote deployment requires an operator-configured protected transport.