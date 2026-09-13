from seckb.pipeline.chunker import chunk_markdown


def test_heading_path_recorded():
    md = "# 文档标题\n\n开头段落。\n\n## 第一节\n\n第一节内容。\n\n### 小节\n\n小节内容。\n"
    chunks = chunk_markdown(md)
    paths = [c.heading_path for c in chunks]
    assert "文档标题 > 第一节" in paths
    assert "文档标题 > 第一节 > 小节" in paths


def test_long_section_splits_with_overlap():
    paragraphs = [f"para-{i} " + "alpha bravo charlie delta echo foxtrot golf hotel india juliet" for i in range(15)]
    md = "# 长文\n\n" + "\n\n".join(paragraphs) + "\n"
    chunks = chunk_markdown(md, target_tokens=60, max_tokens=100, overlap_tokens=24)
    assert len(chunks) >= 2
    seqs = [c.seq for c in chunks]
    assert seqs == list(range(len(chunks)))
    assert all(c.token_count <= 100 for c in chunks)
    second = chunks[1].content
    assert second.split("\n\n")[0].startswith("para-")


def test_every_chunk_has_content_and_count():
    md = "# A\n\nsome text here\n"
    chunks = chunk_markdown(md)
    assert chunks
    assert all(c.content.strip() for c in chunks)
    assert all(c.token_count > 0 for c in chunks)
