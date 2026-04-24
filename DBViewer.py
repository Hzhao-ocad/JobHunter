
from JobStruct import get_all_jobs


alljobs = get_all_jobs(name="Thea")
print(f"Total jobs in database: {len(alljobs)}")
for job in alljobs:
    print(job["job_title"])