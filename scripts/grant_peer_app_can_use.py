#!/usr/bin/env python3
"""Grant CAN_USE on peer Databricks Apps to arango-workflow-app's service principal.

``app.yaml`` ``app`` resources declare intent, but the target app's ACL must include the
caller SP (client id UUID). Databricks docs: use ``service_principal_name`` = SP client id,
not display name — otherwise the PATCH succeeds silently without granting access.

Peer apps (defaults match app.yaml resource names):
  - arango-gateway-app   (extraction prepare thread → gateway /health + Arango proxy)
  - mcp-arango-agent     (Genie BFF proxy)

Example::

  ./scripts/grant_peer_app_can_use.py --app-name arango-workflow-app
  ./scripts/grant_peer_app_can_use.py --service-principal-id 94364b27-...
"""

from __future__ import annotations

import argparse
import sys


DEFAULT_PEER_APPS = ("arango-gateway-app", "mcp-arango-agent")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--app-name",
        default="arango-workflow-app",
        help="Caller Databricks App whose SP receives CAN_USE on peers",
    )
    p.add_argument(
        "--service-principal-id",
        default="",
        help="Caller SP client id (default: apps.get --app-name)",
    )
    p.add_argument(
        "--peer",
        action="append",
        default=[],
        help="Target app name (repeatable). Default: arango-gateway-app, mcp-arango-agent",
    )
    args = p.parse_args()

    peers = [x.strip() for x in args.peer if (x or "").strip()] or list(DEFAULT_PEER_APPS)

    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.apps import AppAccessControlRequest, AppPermissionLevel
    except ImportError as exc:
        print(f"ERROR: databricks-sdk: {exc}", file=sys.stderr)
        return 1

    try:
        w = WorkspaceClient()
    except Exception as exc:
        print(f"ERROR: WorkspaceClient(): {exc}", file=sys.stderr)
        return 1

    sp_id = (args.service_principal_id or "").strip()
    if not sp_id:
        caller = (args.app_name or "").strip()
        if not caller:
            print("ERROR: --app-name or --service-principal-id required", file=sys.stderr)
            return 2
        try:
            app = w.apps.get(caller)
        except Exception as exc:
            print(f"ERROR: apps.get({caller!r}): {exc}", file=sys.stderr)
            return 1
        sp_id = (getattr(app, "service_principal_client_id", None) or "").strip()
    if not sp_id:
        print("ERROR: could not resolve caller service_principal_client_id", file=sys.stderr)
        return 1

    ok = True
    for peer in peers:
        try:
            w.apps.update_permissions(
                peer,
                access_control_list=[
                    AppAccessControlRequest(
                        service_principal_name=sp_id,
                        permission_level=AppPermissionLevel.CAN_USE,
                    )
                ],
            )
        except Exception as exc:
            print(f"ERROR: CAN_USE on {peer!r} for SP {sp_id!r}: {exc}", file=sys.stderr)
            ok = False
            continue
        print(f"OK: CAN_USE on {peer!r} for caller SP {sp_id!r}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
