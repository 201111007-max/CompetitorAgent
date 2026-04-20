"""LangChain + Langfuse 集成示例"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import Optional
from langfuse import observe
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from config.settings import Config


class ChatBot:
    def __init__(self, model_name: str = "gpt-3.5-turbo"):
        self.llm = ChatOpenAI(model=model_name)
        self.prompt = ChatPromptTemplate.from_messages(
            [("system", "你是一个专业的 AI 助手，擅长解答各种问题。"), ("human", "{question}")]
        )
        self.chain = self.prompt | self.llm | StrOutputParser()

    @observe(name="chatbot_answer")
    def answer(self, question: str) -> str:
        response = self.chain.invoke({"question": question})
        return response


@observe(name="search_knowledge_base")
def search_knowledge_base(query: str) -> Optional[str]:
    knowledge_base = {
        "python": "Python 是一种高级编程语言，由 Guido van Rossum 于 1991 年创建。",
        "langchain": "LangChain 是一个用于开发 LLM 应用的框架，提供链式调用、Agent 等功能。",
        "langfuse": "Langfuse 是一个开源的 LLM 工程平台，提供追踪、评估、Prompt 管理等功能。",
    }
    return knowledge_base.get(query.lower(), None)


@observe(name="enhanced_qa")
def enhanced_qa(question: str) -> dict:
    keywords = question.lower().split()
    for keyword in keywords:
        if keyword in ["python", "langchain", "langfuse"]:
            kb_result = search_knowledge_base(keyword)
            if kb_result:
                return {"source": "knowledge_base", "answer": kb_result}

    bot = ChatBot()
    answer = bot.answer(question)
    return {"source": "llm", "answer": answer}


if __name__ == "__main__":
    print("=== LangChain + Langfuse 示例 ===\n")

    result = enhanced_qa("什么是 Langfuse？")
    print(f"问题：什么是 Langfuse？")
    print(f"答案：{result['answer']}")
    print(f"来源：{result['source']}\n")

    result2 = enhanced_qa("Python 有什么特点？")
    print(f"问题：Python 有什么特点？")
    print(f"答案：{result2['answer']}")
    print(f"来源：{result2['source']}\n")

    print(f"查看追踪数据请访问：{Config.LANGFUSE_HOST}")
    print("确保 Langfuse 服务已启动")
