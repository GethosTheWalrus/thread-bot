"""Thin adapter around Temporal schedules; database trigger state remains authoritative."""
async def create_or_update_schedule(client, trigger_id, cron, timezone_name="UTC", overlap="skip"):
    from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleSpec, ScheduleOverlapPolicy
    policy=ScheduleOverlapPolicy.SKIP if overlap=="skip" else ScheduleOverlapPolicy.BUFFER_ONE
    schedule=Schedule(action=ScheduleActionStartWorkflow("TriggerDispatchWorkflow", {"trigger_id":str(trigger_id)}, id=f"agent-dispatch:{trigger_id}", task_queue="threadbot-agent"),spec=ScheduleSpec(cron_expressions=[cron],time_zone_name=timezone_name),policy=policy)
    schedule_id=f"agent-schedule:{trigger_id}"
    try:
        handle=client.get_schedule_handle(schedule_id)
        await handle.update(lambda _: schedule)
    except Exception:
        await client.create_schedule(schedule_id,schedule)
    return schedule_id

async def delete_schedule(client, trigger_id):
    await client.get_schedule_handle(f"agent-schedule:{trigger_id}").delete()

async def pause_schedule(client, trigger_id):
    await client.get_schedule_handle(f"agent-schedule:{trigger_id}").pause("trigger paused")

async def resume_schedule(client, trigger_id):
    await client.get_schedule_handle(f"agent-schedule:{trigger_id}").unpause("trigger resumed")

async def reconcile_schedules(client, triggers):
    """Reconcile active DB schedule triggers; inactive schedules are removed."""
    desired={f"agent-schedule:{trigger.id}" for trigger in triggers if trigger.is_active and trigger.trigger_type=="schedule"}
    for trigger in triggers:
        schedule_id=f"agent-schedule:{trigger.id}"
        if trigger.is_active and trigger.trigger_type=="schedule":
            await create_or_update_schedule(client,trigger.id,trigger.config["cron"],trigger.config.get("timezone","UTC"),trigger.config.get("overlap","skip"))
        elif schedule_id not in desired:
            try: await client.get_schedule_handle(schedule_id).delete()
            except Exception: pass
    return {"reconciled":len(desired)}
