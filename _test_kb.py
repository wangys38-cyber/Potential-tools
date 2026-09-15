import sys
sys.path.insert(0, '.')
from services.ai.knowledge_base import get_knowledge_base

kb = get_knowledge_base(1)

# 搜索 Santos 计划相关内容
results = kb.collection.query(
    query_texts=['Santos 计划 Schedule'],
    n_results=5
)
print('检索结果:')
for i, doc in enumerate(results['documents'][0]):
    print(f'{i+1}. {doc[:300]}...')
    print(f'   来源: {results["metadatas"][0][i].get("title", "")}')
    print()
