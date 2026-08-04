from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

def _match(value, field):
    if field == "*": return True
    for part in field.split(","):
        if part.startswith("*/"):
            try:
                if value % int(part[2:]) == 0:return True
            except ValueError: pass
        else:
            try:
                if value == int(part):return True
            except ValueError: pass
    return False

def next_occurrences(cron:str, timezone_name="UTC", count=5, start=None):
    fields=cron.split()
    if len(fields)!=5: raise ValueError("cron must contain five fields")
    zone=ZoneInfo(timezone_name); current=(start or datetime.now(timezone.utc)).astimezone(zone).replace(second=0,microsecond=0)+timedelta(minutes=1); result=[]
    for _ in range(60*24*366*2):
        if (_match(current.minute,fields[0]) and _match(current.hour,fields[1]) and _match(current.day,fields[2]) and _match(current.month,fields[3]) and _match(current.weekday(),fields[4].replace("7","0"))):
            result.append(current.astimezone(timezone.utc));
            if len(result)>=count:return result
        current+=timedelta(minutes=1)
    raise ValueError("cron has no occurrence in preview range")

def preview(cron, timezone_name="UTC", count=5):
    return {"timezone":timezone_name,"occurrences":next_occurrences(cron,timezone_name,count),"assumptions":["five-field cron","minute precision","DST gaps are skipped and repeated wall times are represented once"]}
