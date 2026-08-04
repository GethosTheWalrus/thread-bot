from datetime import timedelta
from temporalio import workflow
with workflow.unsafe.imports_passed_through():
    from app.activities.retention_activities import retain_expired_artifacts

@workflow.defn
class ArtifactRetentionWorkflow:
    @workflow.run
    async def run(self, args=None):
        return await workflow.execute_activity(retain_expired_artifacts, args or {}, start_to_close_timeout=timedelta(minutes=10))
