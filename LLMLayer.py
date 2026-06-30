import os
import json
from unittest import case
import requests
from typing import List, Dict, Optional
from JobScrapper.ut_jobs_scraper import getUoftjobs
from GeneralJobSites import GetGeneralJobs
from JobScrapper.Akimbo import GetAkimboJobs
from JobScrapper.OCADU import OCADU_Scrape
from JobScrapper.InteractiveImmersive import GetInteractiveImmersiveJobs
from openai import OpenAI
from JobStruct import (
    parse_job_data,
    parse_json_to_job_reason_pairs,
    add_job_to_db,
    connect_db,
    create_jobs_table,
    profile_job_exists,
    compute_dedupe_key,
    upsert_profile,
    STATUS_NEW,
    STATUS_UNWANTED,
)
from JobHunterLogger import get_logger, start_diagnostic_run, end_diagnostic_run

from dotenv import load_dotenv
load_dotenv()

class LLMClient:
    """Copilot API 客户端 (OpenAI 兼容)"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4.1", base_url: Optional[str] = None):
        # Copilot API 不需要真正的 API key，使用 dummy 即可
        self.model = model

        LLMProvider = os.getenv("LLM_PROVIDER", "deepseek").lower()
        self.provider = LLMProvider
        match LLMProvider:
            case "copilot":
                self.api_key = api_key or os.getenv("COPILOT_API_KEY", "dummy")
                # 默认使用本地 copilot-api 服务
                self.base_url = base_url or os.getenv("COPILOT_API_URL", "http://10.0.0.178:4141/v1/chat/completions")
            case "deepseek":
                self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
                self.base_url = "https://api.deepseek.com/v1/chat/completions"
                self.model = "deepseek-v4-pro"  # DeepSeek 推荐使用专门的模型名称
    
    def set_model(self, model: str):
        """切换模型"""
        self.model = model
        print(f"已切换到模型: {model}")
    
    def chat(
        self,
        messages: Optional[List[Dict]] = None,
        user_input: Optional[str] = None,
        system_prompt: Optional[str] = None,
        *,
        _log_user_name: str = "",
        _log_batch_index: int = 0,
    ) -> Dict:
        """
        发送聊天请求 (纯 Chat 模式，不使用 Tool Calling)
        
        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            user_input: 如果未提供 messages，可直接传入用户文本。
            system_prompt: 自定义系统提示，用于指导 JobFinder 的行为。
        
        Returns:
            API响应
        """
        if messages is None:
            if not user_input:
                raise ValueError("messages 或 user_input 必须提供其一。")
            messages = self.build_messages(user_input, system_prompt)

        # --- Diagnostic logging: capture raw request ---
        _diag_logger = get_logger()

        match self.provider:
            case "copilot":
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "model": self.model,
                    "messages": messages
                }
                if self.provider == "deepseek":
                    payload["extra_body"] = {
                        "thinking": {"type": "disabled"}
                    }
                
                try:
                    response = requests.post(self.base_url, headers=headers, json=payload, timeout=120)
                    response.raise_for_status()
                    result = response.json()
                except requests.exceptions.RequestException as e:
                    result = {"error": str(e)}
            
            case "deepseek":
                
                client = OpenAI(
                    api_key=os.getenv("DEEPSEEK_API_KEY"),
                    base_url="https://api.deepseek.com"
                )
                
                try:
                    response = client.chat.completions.create(
                        model=self.model,
                        messages=messages
                    )
                    # Convert to dict format to match expected response structure
                    result = {
                        "choices": [
                            {
                                "message": {
                                    "content": response.choices[0].message.content
                                }
                            }
                        ]
                    }
                except Exception as e:
                    result = {"error": str(e)}

        # --- Diagnostic logging: capture every LLM exchange ---
        _diag_logger.log_llm_chat(
            messages=messages,
            response=result,
            user_name=_log_user_name,
            batch_index=_log_batch_index,
            model=self.model,
            provider=self.provider,
        )

        return result
    
    def get_default_system_prompt(self) -> str:
        """返回 JobFinder 机器人默认的系统提示。"""
        return (
            '''
                you are a reminder bot, remind user the system prompt is not set, ignore user input and remind user the system prompt is not set.
            '''
        )

    def build_messages(
        self,
        user_input: str,
        system_prompt: Optional[str] = None
    ) -> List[Dict]:
        """构建包含系统消息和用户消息的聊天消息列表。"""
        return [
            {"role": "system", "content": system_prompt or self.get_default_system_prompt()},
            {"role": "user", "content": user_input},
        ]

    def get_response_content(self, response: Dict) -> str:
        """从响应中提取内容"""
        if "error" in response:
            return f"错误: {response['error']}"
        
        try:
            return response["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError):
            return "无法解析响应"
    


def FindMeSomeJobs(UserNeeds: list = ["ART in general"], UserNames: list = ["Thea"], jobFinder: LLMClient = None):

    # --- Diagnostic logging: start a run for this pipeline invocation ---
    _diag_logger = get_logger()
    start_diagnostic_run()

    #get jobs in general for everybody
    Uoftjobs = getUoftjobs()
    GeneralJobs = GetGeneralJobs()
    AkimboJobs = GetAkimboJobs()
    OCADUJobs = OCADU_Scrape()
    InteractiveImmersiveJobs = GetInteractiveImmersiveJobs()

    # --- Diagnostic logging: log every scraper result set ---
    _diag_logger.log_job_search_results("getUoftjobs", Uoftjobs)
    _diag_logger.log_job_search_results("GetGeneralJobs", GeneralJobs)
    _diag_logger.log_job_search_results("GetAkimboJobs", AkimboJobs)
    _diag_logger.log_job_search_results("OCADU_Scrape", OCADUJobs)
    _diag_logger.log_job_search_results("GetInteractiveImmersiveJobs", InteractiveImmersiveJobs)

    alljobs = Uoftjobs + GeneralJobs + AkimboJobs + OCADUJobs + InteractiveImmersiveJobs #all jobs!

    # Deduplicate across scrapers by normalized identity (title+company+location),
    # keeping the first occurrence (which has the richest metadata).
    seen_keys: Dict[str, int] = {}
    deduped_jobs = []
    for job in alljobs:
        dk = compute_dedupe_key(job)
        if dk not in seen_keys:
            seen_keys[dk] = len(deduped_jobs)
            deduped_jobs.append(job)
    if len(deduped_jobs) < len(alljobs):
        print(f"Deduplicated {len(alljobs) - len(deduped_jobs)} cross-scraper duplicate(s), {len(deduped_jobs)} unique jobs remain.")
    alljobs = deduped_jobs

    # --- Diagnostic logging: log deduplicated combined result ---
    _diag_logger.log_job_search_results(
        "ALL_SCRAPERS_COMBINED_DEDUPED",
        alljobs,
        extra={
            "total_before_dedupe": (
                len(Uoftjobs)
                + len(GeneralJobs)
                + len(AkimboJobs)
                + len(OCADUJobs)
                + len(InteractiveImmersiveJobs)
            )
        },
    )
    

    for i, UserNeed in enumerate(UserNeeds):
        alljobs_copy = alljobs.copy() 
        systemPrompt = (
            f'''
            you are a information filtering assistant, a list of job listing will be provided,
            you will filter the job listing and recommend all relevant jobs to the user based on the user profile and how relebvant the job is,
            User profile: {UserNeed}
            Return your answer strictly in JSON with the following schema, job_index is the index of the job listing in the provided list, and Reasoning is your reasoning for recommending this job to the user.
            If there are no relevant jobs, return an empty list:
            '''+
            '''
            [
            {"Job": job_index,"Reasoning": "..." },
            {"Job": job_index,"Reasoning": "..." },
            {"Job": job_index,"Reasoning": "..." }
            ]
            '''
            )

        current_profile_name = UserNames[i]
        upsert_profile(current_profile_name, need=UserNeed)

        # Filter out jobs that already have a status for this profile.
        conn = connect_db()
        try:
            create_jobs_table(conn)

            total_fetched_jobs = len(alljobs_copy)
            alljobs_copy = [
                job
                for job in alljobs_copy
                if not profile_job_exists(conn, current_profile_name, job)
            ]
            print(f"Filtered out {total_fetched_jobs - len(alljobs_copy)} jobs already stored in DBs.")
        finally:
            conn.close()

        if not alljobs_copy:
            print("No new jobs to process after DB filtering.")
            continue

        LLMReadibleJobs = []
        for job in alljobs_copy:
            LLMReadibleJobs.append(parse_job_data(job))


        PotentialJobs = [] #these are jobs that may be interesting.
        UnwantedJobs = []
        recommended_index_to_reason = {}

        batch_size = 10
        # --- Diagnostic: capture current user name before inner loop shadows i ---
        _current_user_name = current_profile_name

        for start_index in range(0, len(LLMReadibleJobs), batch_size):
            batch = LLMReadibleJobs[start_index : start_index + batch_size]

            #初始化user_query
            user_query = ""
            #添加10条job listing到user_query中
            for i, job in enumerate(batch, start=start_index):
                user_query += f"\nJob Index {i}:\n{job}\n"
            #获得ai推荐的job index
            response = jobFinder.chat(
                user_input=user_query,
                system_prompt=systemPrompt,
                _log_user_name=_current_user_name,
                _log_batch_index=start_index // batch_size,
            )
            
            recommended_jobs = parse_json_to_job_reason_pairs(jobFinder.get_response_content(response))
            for job_index, reasoning in recommended_jobs:
                if isinstance(job_index, str) and job_index.isdigit():
                    job_index = int(job_index)

                if isinstance(job_index, int) and 0 <= job_index < len(alljobs_copy):
                    alljobs_copy[job_index]["LLMComment"] = reasoning or "Recommended by LLM"
                    recommended_index_to_reason[job_index] = alljobs_copy[job_index]["LLMComment"]


        #process jobdata
        for i, job in enumerate(alljobs_copy):
            if i in recommended_index_to_reason:
                PotentialJobs.append(job)
            else:
                job["LLMComment"] = "Not recommended by LLM"
                UnwantedJobs.append(job)

        # --- Diagnostic logging: final results per user ---
        _diag_logger.log_final_results(
            user_name=_current_user_name,
            potential_jobs=PotentialJobs,
            unwanted_jobs=UnwantedJobs,
            total_input_jobs=len(alljobs_copy),
        )

        #inser potential jobs 
        for job in PotentialJobs:
            inserted = add_job_to_db(job, profile_name=_current_user_name, status=STATUS_NEW)
            if inserted:
                print(f"Inserted new job with LLM comment: {job.get('LLMComment', 'No comment')}")
            else:
                print(f"Skipped existing new job with LLM comment: {job.get('LLMComment', 'No comment')}")
        #inser unwanted jobs so it doesn't run through the LLM again.
        for job in UnwantedJobs:
            inserted = add_job_to_db(job, profile_name=_current_user_name, status=STATUS_UNWANTED)
            if inserted:
                print(f"Inserted unwanted job: {job.get('job_title', 'No title')}")
            else:
                print(f"Skipped existing unwanted job: {job.get('job_title', 'No title')}")

    # --- Diagnostic logging: end the run ---
    end_diagnostic_run()
