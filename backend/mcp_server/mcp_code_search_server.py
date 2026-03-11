#!/usr/bin/env python3
"""
代码知识搜索 FastMCP Server
使用 fastmcp 框架实现 streaming 模式的代码知识搜索
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional
from http import HTTPStatus

# 添加项目根目录到路径
current_file = os.path.abspath(__file__)
project_root = os.path.dirname(current_file)
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from openai import OpenAI
import dashscope
from dashscope import get_tokenizer

# 导入 fastmcp
from fastmcp import FastMCP

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 配置常量
QDRANT_COLLECTION_NAME = "code_knowledge_2048"
TOP_K = 20
RERANK_TOP_K = 10
MAX_DOC_TOKENS = 1200
OVERLAP_TOKENS = 256
MAX_CHUNKS_PER_DOC = 3
BATCH_TOKEN_LIMIT = 28000
MODEL_NAME = "qwen3-rerank"

# 全局变量
qdrant_client = None
embedding_client = None
mcp_server = None

def init_clients():
    """初始化客户端"""
    global qdrant_client, embedding_client

    logger.info("Initializing clients...")

    # 初始化 Qdrant 客户端
    qdrant_client = QdrantClient(
        host=os.getenv("QDRANT_HOST", "localhost"),
        port=int(os.getenv("QDRANT_PORT", "6333"))
    )

    # 初始化 Embedding 客户端
    embedding_client = OpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY", ""),
        base_url=os.getenv("EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    )

    logger.info("Clients initialized successfully")

def create_query_vector(query: str) -> List[float]:
    """创建查询向量"""
    resp = embedding_client.embeddings.create(
        model="text-embedding-v4",
        input=[query],
        dimensions=2048,
    )
    return resp.data[0].embedding

def search_qdrant(query_vector: List[float], score_threshold: float) -> List[Dict[str, Any]]:
    """搜索 Qdrant 数据库"""
    search_results = qdrant_client.query_points(
        collection_name=QDRANT_COLLECTION_NAME,
        query=query_vector,
        query_filter=None,
        limit=TOP_K,
        score_threshold=score_threshold,
        with_payload=True,
        with_vectors=False
    )

    # 转换结果格式
    results = []
    for hit in search_results.points:
        result = {
            "id": hit.id,
            "score": hit.score,
            "payload": hit.payload
        }
        results.append(result)

    logger.info(f"Qdrant search returned {len(results)} results")
    return results

def chunk_document(method_sig: str, knowledge: str, source_code: str, tokenizer) -> List[str]:
    """将文档分割成块"""
    header = f"Method: {method_sig}\nDescription: {knowledge}\nSource:\n"
    header_tokens = tokenizer.encode(header)

    code_tokens = tokenizer.encode(source_code)
    available_code_space = MAX_DOC_TOKENS - len(header_tokens)

    # 处理巨大的 header
    if available_code_space < 100:
        header_tokens = header_tokens[:MAX_DOC_TOKENS - 100]
        header = tokenizer.decode(header_tokens)
        available_code_space = 100

    chunks = []
    chunk_to_result_map = []

    # 分块逻辑
    if len(code_tokens) <= available_code_space:
        # 一个块
        final_text = header + source_code
        chunks.append(final_text)
        chunk_to_result_map.append(0)
    else:
        # 多个块
        stride = available_code_space - OVERLAP_TOKENS
        for i in range(0, len(code_tokens), stride):
            chunk_tokens = code_tokens[i:i + available_code_space]
            chunk_code = tokenizer.decode(chunk_tokens)
            final_text = header + chunk_code
            chunks.append(final_text)
            chunk_to_result_map.append(0)

            if len(chunks) >= MAX_CHUNKS_PER_DOC:
                break

    return chunks, chunk_to_result_map

def rerank_documents(query: str, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Rerank search results using DashScope TextReRank model.
    Handles token limits by:
    1. Splitting long documents into chunks (sliding window)
    2. Batching chunks into multiple API calls if total tokens exceed limit
    3. Aggregating scores using Max-Pooling
    Ensures ALL results are processed.
    """
    if not results:
        return results

    try:
        # Configuration for qwen3-rerank
        MODEL_NAME = "qwen3-rerank"
        MAX_DOC_TOKENS = 1200       # Token limit per chunk
        OVERLAP_TOKENS = 256        # Overlap between code chunks
        MAX_CHUNKS_PER_DOC = 3      # Prevent one huge doc from eating too much (still needed for efficiency)
        BATCH_TOKEN_LIMIT = 28000   # Token limit per API request

        try:
            tokenizer = get_tokenizer(MODEL_NAME)
        except Exception as e:
            logger.warning(f"Failed to get tokenizer: {e}, skipping rerank")
            return results

        # Step 1: Generate all chunks for all documents
        all_chunks = []
        chunk_to_result_map = [] # chunk_global_index -> original_result_index
        
        for res_idx, res in enumerate(results):
            method_sig = res.get("method", "")
            knowledge = res.get("knowledge", "")
            source_code = res.get("method_source_code", "")

            # Construct Header
            header = f"Method: {method_sig}\nDescription: {knowledge}\nSource:\n"
            header_tokens = tokenizer.encode(header)
            
            code_tokens = tokenizer.encode(source_code)
            available_code_space = MAX_DOC_TOKENS - len(header_tokens)
            
            # Handle huge header
            if available_code_space < 100:
                header_tokens = header_tokens[:MAX_DOC_TOKENS - 100]
                header = tokenizer.decode(header_tokens)
                available_code_space = 100

            # Chunking Logic
            if len(code_tokens) <= available_code_space:
                # One chunk
                final_text = header + source_code
                all_chunks.append(final_text)
                chunk_to_result_map.append(res_idx)
            else:
                # Split
                start = 0
                chunk_count = 0
                while start < len(code_tokens) and chunk_count < MAX_CHUNKS_PER_DOC:
                    end = start + available_code_space
                    chunk_code_tokens = code_tokens[start:end]
                    chunk_code_text = tokenizer.decode(chunk_code_tokens)
                    final_text = header + chunk_code_text
                    
                    all_chunks.append(final_text)
                    chunk_to_result_map.append(res_idx)
                    
                    chunk_count += 1
                    if end >= len(code_tokens):
                        break
                    start += (available_code_space - OVERLAP_TOKENS)

        if not all_chunks:
            return results

        # Step 2: Create Batches based on Token Limit
        batches = []
        current_batch = []
        current_batch_tokens = 0
        current_batch_indices = [] # Global indices of chunks in this batch

        for i, chunk in enumerate(all_chunks):
            # Estimate tokens (approximation usually fine, but better to be safe)
            # We encode again to be precise for batching, or we could have stored lengths.
            # To be efficient, we'll re-encode or assume length from creation.
            # Let's re-encode quickly to be safe as `len(chunk)` is chars not tokens.
            chunk_token_len = len(tokenizer.encode(chunk))
            
            if current_batch_tokens + chunk_token_len > BATCH_TOKEN_LIMIT:
                # Finish current batch
                if current_batch:
                    batches.append({"docs": current_batch, "indices": current_batch_indices})
                # Start new batch
                current_batch = [chunk]
                current_batch_indices = [i]
                current_batch_tokens = chunk_token_len
            else:
                current_batch.append(chunk)
                current_batch_indices.append(i)
                current_batch_tokens += chunk_token_len

        # Add last batch
        if current_batch:
            batches.append({"docs": current_batch, "indices": current_batch_indices})

        logger.info(f"Reranking {len(all_chunks)} chunks in {len(batches)} batches for query: {query}")

        # Step 3: Process Batches
        doc_max_scores = {} # original_res_idx -> max_score

        for batch_idx, batch in enumerate(batches):
            batch_docs = batch["docs"]
            batch_indices = batch["indices"]
            
            try:
                resp = dashscope.TextReRank.call(
                    model=MODEL_NAME,
                    query=query,
                    documents=batch_docs,
                    top_n=len(batch_docs),
                    return_documents=False
                )

                if resp.status_code == HTTPStatus.OK:
                    for item in resp.output.results:
                        # item.index is relative to the batch
                        local_idx = item.index
                        score = item.relevance_score
                        
                        # Find global chunk index -> original result index
                        global_chunk_idx = batch_indices[local_idx]
                        original_res_idx = chunk_to_result_map[global_chunk_idx]
                        
                        # Max-Pooling Aggregation
                        if original_res_idx not in doc_max_scores:
                            doc_max_scores[original_res_idx] = score
                        else:
                            if score > doc_max_scores[original_res_idx]:
                                doc_max_scores[original_res_idx] = score
                else:
                    logger.error(f"Rerank API failed for batch {batch_idx}: {resp.code} - {resp.message}")
                    # Continue to next batch, some scores might be missing (default to original sorting)

            except Exception as e:
                logger.error(f"Rerank exception for batch {batch_idx}: {e}")

        # Step 4: Apply Scores & Sort
        # Only update scores if we got a rerank score
        for res_idx, max_score in doc_max_scores.items():
            results[res_idx]["score"] = max_score

        # Sort: Reranked items (high scores) > Un-reranked items (None or old vector scores)
        # Note: If batch failed, some items might keep vector scores. 
        # Since vector scores are < 1.0, and rerank scores can be high, this is usually acceptable fallback.
        results.sort(key=lambda x: x["score"] if x["score"] is not None else -1, reverse=True)

        logger.info("Rerank processing complete")
        return results

    except Exception as e:
        logger.error(f"Rerank global exception: {e}")
        return results

# 创建 FastMCP 服务器
mcp_server = FastMCP("code-knowledge-search")

@mcp_server.tool()
async def search_code_knowledge(
    query: str,
    score_threshold: float = 0.3
) -> List[Dict[str, Any]]:
    """
    Search Myjo (麦巨)'s luim (大部队) backend code knowledge base to understand business implementation methods
    """
    try:
        logger.info(f"Searching for code knowledge with query: '{query}', threshold: {score_threshold}")

        # 步骤1: 创建查询向量
        query_vector = create_query_vector(query)

        # 步骤2: 搜索 Qdrant
        search_results = search_qdrant(query_vector, score_threshold)

        # 步骤3: 重排
        rerank_results = rerank_documents(query, search_results)

        # 步骤4: 返回最终结果
        final_results = rerank_results[:RERANK_TOP_K]

        # 格式化结果
        formatted_results = []
        for i, result in enumerate(final_results, 1):
            formatted_result = {
                "rank": i,
                "score": result.get("score", 0),
                "method": result.get("payload", {}).get("method", ""),
                "call_hash": result.get("payload", {}).get("call_hash", ""),
                "knowledge": result.get("payload", {}).get("knowledge", "")[:500],
                "method_source_code": result.get("payload", {}).get("method_source_code", ""),
                "table_definition": result.get("payload", {}).get("table_definition", ""),
                "deployed_in_module": result.get("payload", {}).get("deployed_in_module", ""),
                "lag": result.get("payload", {}).get("lag", 0)
            }
            formatted_results.append(formatted_result)

        return formatted_results

    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise


def mcp_main():
    """主函数"""
    # 初始化客户端
    init_clients()

    # 启动服务器
    asyncio.run(mcp_server.run_http_async(transport="streamable-http", host="0.0.0.0", port=18000, json_response=True))