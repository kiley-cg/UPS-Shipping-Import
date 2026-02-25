"""
New tools to add to syncore_server.py
--------------------------------------
Paste these two functions into syncore_server.py alongside the other
@mcp.tool() definitions (e.g. after the JOBS section).

These give Claude the ability to read and write Job Log entries in Syncore,
which is what the UPS tracking import uses.
"""

# ============================================================
# JOB LOG (2 new tools)
# ============================================================

@mcp.tool()
async def get_job_logs(job_id: int) -> str:
    """Get all Job Log entries for a specific Syncore job.

    Shows the full log history including system entries (status changes)
    and user entries (manual notes, UPS tracking imports, etc.).

    Args:
        job_id: The Syncore job ID (the 5-digit job number, e.g. 31987)
    """
    result = await _api_get(f"/orders/jobs/{job_id}/logs")
    return json.dumps(result, indent=2)


@mcp.tool()
async def add_job_log(job_id: int, description: str) -> str:
    """Add a Job Log entry to a Syncore job.

    Creates a new entry in the Job Log tab visible on the job detail page.
    Use this to record tracking numbers, shipping costs, status updates,
    or any other notes on a job.

    Args:
        job_id: The Syncore job ID (the 5-digit job number, e.g. 31987)
        description: The text content of the log entry. Multi-line text is supported.

    Example description for UPS tracking:
        "UPS Tracking Import — 02/25/2026
        PO: 31987-1
        Packages: 2
        Tracking Number(s):
          1Z585FA50368937651
          1Z0671AE0343033420
        UPS Shipping Cost: $38.94"
    """
    result = await _api_post(f"/orders/jobs/{job_id}/logs", {"description": description})
    return json.dumps(result, indent=2)
