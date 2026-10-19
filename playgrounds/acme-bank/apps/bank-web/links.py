"""Links into the Gamma console: the exact item of one call (its log entry, its trace, the decision about it), the dashboard that
shows what a run cost, the lists those items belong to, and the console's own pages.

Gamma opens one item by a path (`observe/logs/<request id>?apiId=`, `observe/tracing/<api id>/<trace id>`, `authz/observe/logs/<event id>?apiId=`),
and a list or a dashboard from `?q=` (base64url of a JSON object, without padding) and `v=1`. A time range of a `q` is absolute here: a relative
one ("the last hour") is empty an hour after the call.
"""
import base64
import json
from urllib.parse import quote

WORKSPACE_DASHBOARD = "ai-workspace-overview"    # the console's own dashboard of an AI workspace: its filters are the workspace and the person


def _segment(value: str) -> str:
    """An id as one segment of a path: whatever the platform called it, it cannot leave the segment."""
    return quote(str(value), safe="")


class Links:
    def __init__(self, gamma_url: str, env: str):
        self.base = f"{gamma_url.rstrip('/')}/environments/{env.lower()}"

    # -- the item of one call -------------------------------------------------------------------------------------------
    def log(self, api_id: str, request_id: str) -> str:
        """The log entry of one gateway request: Gamma needs the API that served it as well."""
        return f"{self.base}/aim/observe/logs/{_segment(request_id)}?apiId={_segment(api_id)}"

    def decision(self, api_id: str, event_id: str) -> str:
        """The authorization decision, by the id of its event (not the request's): in the Decisions of the console."""
        return f"{self.base}/authz/observe/logs/{_segment(event_id)}?apiId={_segment(api_id)}"

    def trace(self, api_id: str | None, trace_id: str | None = None, window: tuple[int, int] | None = None) -> str | None:
        """One trace of an API, else the traces of that API (those of `window` where there is one: epoch ms)."""
        if not api_id:
            return None
        page = f"{self.base}/aim/observe/tracing/{_segment(api_id)}"
        if trace_id:
            return f"{page}/{_segment(trace_id)}"
        return f"{page}?q={self._q([], window)}&v=1" if window else page

    def spend_dashboard(self, workspace_id: str, application_id: str | None, window: tuple[int, int]) -> str:
        """What a workspace's person spent in a window of time: the console's dashboard of the workspace, filtered on both and on the window."""
        conditions = [{"field": "API_PRODUCT", "label": "AI Workspace", "operator": "eq", "value": [workspace_id]}]
        if application_id:
            conditions.append({"field": "APPLICATION", "label": "User", "operator": "eq", "value": [application_id]})
        return f"{self.base}/aim/observe/dashboards/{WORKSPACE_DASHBOARD}?q={self._q(conditions, window)}&v=1"

    # -- the lists those items belong to, filtered on the call, for the item that is not there ----------------------
    def logs_list(self, request_id: str, window: tuple[int, int]) -> str:
        return self._filtered("aim/observe/logs", "REQUEST_ID", "Request ID", request_id, window)

    def decisions_list(self, request_id: str, window: tuple[int, int]) -> str:
        return self._filtered("authz/observe/logs", "REQUEST_ID", "Request ID", request_id, window)

    # -- the pages ----------------------------------------------------------------------------------------------------------
    def spend(self, workspace_id: str | None) -> str | None:
        return f"{self.base}/aim/ai-workspaces/{workspace_id}/spend" if workspace_id else None

    def workspaces(self) -> str:
        return f"{self.base}/aim/ai-workspaces"

    def pages(self) -> dict[str, str]:
        """The console's evidence pages: the list an item belongs to, when the item is not there."""
        return {"dashboards": f"{self.base}/aim/observe/dashboards", "logs": f"{self.base}/aim/observe/logs",
                "tracing": f"{self.base}/aim/observe/tracing", "decisions": f"{self.base}/authz/observe/logs"}

    # -- the console's own query --------------------------------------------------------------------------------------------
    @staticmethod
    def _q(conditions: list[dict], window: tuple[int, int] | None) -> str:
        query = {"c": conditions, **({"t": {"type": "absolute", "from": window[0], "to": window[1]}} if window else {})}
        return base64.urlsafe_b64encode(json.dumps(query, separators=(",", ":")).encode()).rstrip(b"=").decode()

    def _filtered(self, page: str, field: str, label: str, value: str, window: tuple[int, int]) -> str:
        condition = {"field": field, "label": label, "operator": "eq", "value": [value]}
        return f"{self.base}/{page}?q={self._q([condition], window)}&v=1"
