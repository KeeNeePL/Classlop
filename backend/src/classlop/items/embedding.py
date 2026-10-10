from classlop.shared.llm import embeddings


async def embed(texts: list[str]) -> list[list[float]]:
    return await embeddings().aembed_documents(texts)


async def embed_query(text: str) -> list[float]:
    return (await embed([text]))[0]
