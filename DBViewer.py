
from JobStruct import get_all_jobs


alljobs = get_all_jobs(name="Thea")
print(f"Total jobs in database: {len(alljobs)}")
for job in alljobs:
    print(f"{job.get('status', 'unknown')}: {job['job_title']}")
