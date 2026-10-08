"""Generate realistic PDF research papers for real-world RAG validation."""

import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors


def build_paper(filename: str, title: str, authors: str, abstract: str, sections: list):
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        rightMargin=54,
        leftMargin=54,
        topMargin=54,
        bottomMargin=54,
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'PaperTitle',
        parent=styles['Heading1'],
        fontSize=20,
        leading=24,
        alignment=1,  # Centered
        spaceAfter=12,
        textColor=colors.HexColor("#1A202C")
    )

    author_style = ParagraphStyle(
        'PaperAuthors',
        parent=styles['Normal'],
        fontSize=11,
        leading=14,
        alignment=1,
        spaceAfter=20,
        textColor=colors.HexColor("#4A5568")
    )

    abstract_heading = ParagraphStyle(
        'AbstractHeading',
        parent=styles['Heading3'],
        fontSize=12,
        leading=16,
        alignment=1,
        spaceAfter=6,
        textColor=colors.HexColor("#2D3748")
    )

    abstract_style = ParagraphStyle(
        'PaperAbstract',
        parent=styles['Italic'],
        fontSize=10,
        leading=14,
        alignment=4,  # Justified
        spaceAfter=24,
        leftIndent=24,
        rightIndent=24,
        textColor=colors.HexColor("#2D3748")
    )

    h1_style = ParagraphStyle(
        'PaperH1',
        parent=styles['Heading2'],
        fontSize=14,
        leading=18,
        spaceBefore=14,
        spaceAfter=8,
        textColor=colors.HexColor("#1A365D")
    )

    body_style = ParagraphStyle(
        'PaperBody',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        alignment=4,
        spaceAfter=10,
        textColor=colors.HexColor("#2D3748")
    )

    story = [
        Paragraph(title, title_style),
        Paragraph(authors, author_style),
        Paragraph("Abstract", abstract_heading),
        Paragraph(abstract, abstract_style),
        Spacer(1, 10),
    ]

    for sec in sections:
        if len(sec) == 3:
            section_title, paragraphs, new_page = sec
        else:
            section_title, paragraphs = sec
            new_page = False

        if isinstance(paragraphs, str):
            paragraphs = [paragraphs]

        if new_page:
            story.append(PageBreak())
        if section_title:
            story.append(Paragraph(section_title, h1_style))
        for p in paragraphs:
            story.append(Paragraph(p, body_style))
            story.append(Spacer(1, 4))

    doc.build(story)
    print(f"Generated {filename}")


def generate_all_papers(output_dir: str):
    os.makedirs(output_dir, exist_ok=True)

    # 1. Attention Is All You Need
    build_paper(
        os.path.join(output_dir, "attention_is_all_you_need.pdf"),
        "Attention Is All You Need",
        "Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez, Łukasz Kaiser, Illia Polosukhin",
        "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks "
        "that include an encoder and a decoder. The best performing models also connect the encoder and decoder through "
        "an attention mechanism. We propose a new simple network architecture, the Transformer, based solely on attention "
        "mechanisms, dispensing with recurrence and convolutions entirely. Experiments on two machine translation tasks "
        "show these models to be superior in quality while being more parallelizable and requiring significantly less time to train.",
        [
            (
                "1. Introduction",
                [
                    "Recurrent neural networks, especially long short-term memory (LSTM) and gated recurrent (GRU) neural networks, "
                    "have been firmly established as state of the art approaches in sequence modeling and transduction problems such as "
                    "language modeling and machine translation. Subsequent efforts have since continued to push the boundaries of recurrent "
                    "language models and encoder-decoder architectures.",
                    "Recurrent models typically factor computation along the symbol positions of the input and output sequences. "
                    "Aligning the positions to steps in computation time, they generate a sequence of hidden states h_t, as a function of the "
                    "previous hidden state h_{t-1} and the input for position t. This inherently sequential nature precludes parallelization "
                    "within training examples, which becomes critical at longer sequence lengths.",
                    "The primary contribution of this work is the Transformer, a model architecture eschewing recurrence and instead relying "
                    "entirely on an attention mechanism to draw global dependencies between input and output. The Transformer allows for "
                    "significantly more parallelization and can reach a new state of the art in translation quality after being trained for "
                    "as little as twelve hours on eight P100 GPUs."
                ],
                False
            ),
            (
                "2. Model Architecture",
                [
                    "Most competitive neural sequence transduction models have an encoder-decoder structure. Here, the encoder maps an "
                    "input sequence of symbol representations (x_1, ..., x_n) to a sequence of continuous representations z = (z_1, ..., z_n). "
                    "Given z, the decoder then generates an output sequence (y_1, ..., y_m) of symbols one element at a time. At each step the "
                    "model is auto-regressive, consuming the previously generated symbols as additional input when generating the next.",
                    "The Transformer follows this overall architecture using stacked self-attention and point-wise, fully connected layers "
                    "for both the encoder and decoder. The encoder is composed of a stack of N = 6 identical layers. Each layer has two "
                    "sub-layers: a multi-head self-attention mechanism and a simple, position-wise fully connected feed-forward network. "
                    "We employ a residual connection around each of the two sub-layers, followed by layer normalization."
                ],
                True  # Page 2
            ),
            (
                "3. Multi-Head Attention",
                [
                    "An attention function can be described as mapping a query and a set of key-value pairs to an output, where the query, "
                    "keys, values, and output are all vectors. The output is computed as a weighted sum of the values, where the weight assigned "
                    "to each value is computed by a compatibility function of the query with the corresponding key.",
                    "Instead of performing a single attention function with d_model-dimensional keys, values and queries, we found it beneficial "
                    "to linearly project the queries, keys and values h times with different, learned linear projections to d_k, d_k and d_v "
                    "dimensions, respectively. On each of these projected versions of queries, keys and values we then perform the attention "
                    "function in parallel, yielding d_v-dimensional output values.",
                    "Multi-head attention allows the model to jointly attend to information from different representation subspaces at different "
                    "positions. With a single attention head, averaging inhibits this. In our work we employ h = 8 parallel attention layers, or heads. "
                    "For each of these we use d_k = d_v = d_model / h = 64."
                ],
                False
            ),
            (
                "4. Positional Encoding and Training",
                [
                    "Since our model contains no recurrence and no convolution, in order for the model to make use of the order of the sequence, "
                    "we must inject some information about the relative or absolute position of the tokens in the sequence. To this end, we add "
                    "positional encodings to the input embeddings at the bottoms of the encoder and decoder stacks.",
                    "The positional encodings have the same dimension d_model as the embeddings, so that the two can be summed. There are many "
                    "choices of positional encodings, learned and fixed. In this work, we use sine and cosine functions of different frequencies: "
                    "PE(pos, 2i) = sin(pos / 10000^(2i / d_model)) and PE(pos, 2i+1) = cos(pos / 10000^(2i / d_model)).",
                    "We trained on the standard WMT 2014 English-German dataset consisting of about 4.5 million sentence pairs. On the WMT 2014 "
                    "English-to-German translation task, the big transformer model establishes a new state-of-the-art BLEU score of 28.4."
                ],
                True  # Page 3
            )
        ]
    )

    # 2. Retrieval-Augmented Generation
    build_paper(
        os.path.join(output_dir, "retrieval_augmented_generation.pdf"),
        "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        "Patrick Lewis, Ethan Perez, Aleksandara Piktus, Fabio Petroni, Vladimir Karpukhin, Naman Goyal, Heinrich Küttler, Mike Lewis, Scott Yih, Tim Rocktäschel, Sebastian Riedel, Douwe Kiela",
        "Large pre-trained language models have been shown to store factual knowledge in their parameters, and achieve "
        "state-of-the-art results when fine-tuned on downstream NLP tasks. However, their ability to access and precisely "
        "manipulate knowledge is still limited, and on knowledge-intensive tasks, their performance falls behind task-specific "
        "architectures. We explore a general-purpose fine-tuning recipe for retrieval-augmented generation (RAG) — models which "
        "combine pre-trained parametric and non-parametric memory for language generation.",
        [
            (
                "1. Introduction and Overview",
                [
                    "Pre-trained neural language models learn a substantial amount of in-depth knowledge from data without any explicit "
                    "supervision. While this development is exciting, such models have notable downsides: they cannot easily expand or revise "
                    "their memory, they can produce 'hallucinations', and they struggle to access and precisely manipulate factual knowledge.",
                    "Hybrid models that combine parametric memory (a pre-trained seq2seq transformer) with non-parametric memory (a dense vector "
                    "index of Wikipedia accessed via a neural retriever) can address these issues because knowledge can be directly revised and "
                    "expanded, and accessed predictions can be inspected and traced back to specific source documents.",
                    "The primary contribution of this research is the RAG architecture, which endows pre-trained, parametric-only language models "
                    "with a non-parametric memory using pre-trained Dense Passage Retrieval (DPR) to query a dense vector index of Wikipedia passages. "
                    "We train the retriever and generator end-to-end for knowledge-intensive generation."
                ],
                False
            ),
            (
                "2. Methods: RAG-Sequence vs RAG-Token",
                [
                    "We explore two formulations for combining parametric and non-parametric memory: RAG-Sequence and RAG-Token. Both models "
                    "use an input sequence x to retrieve top-k documents z. When generating the target sequence y, they treat retrieved documents "
                    "as latent variables marginalizing over them.",
                    "In RAG-Sequence, the model uses the same retrieved document to generate the complete sequence. Concretely, it treats the "
                    "retrieved document as a single latent variable that is marginalized over via a top-k approximation to generate the output sequence. "
                    "The probability p(y|x) is calculated as the sum of p(z|x) * p(y|x, z) across top documents.",
                    "In RAG-Token, the model can draw from different latent documents for each token. This allows the generator to synthesize "
                    "content from several passages when producing an answer. The transition probability for each token y_t is computed by marginalizing "
                    "over documents: sum of p(z|x) * p(y_t | x, y_{1:t-1}, z)."
                ],
                True  # Page 2
            ),
            (
                "3. Non-Parametric Memory and Dense Retrieval",
                [
                    "The non-parametric memory component is built using Dense Passage Retrieval (DPR). DPR uses a dual-encoder architecture: "
                    "a query encoder q(x) and a passage encoder d(z), both based on BERT. The retrieval score is the dot product of the query "
                    "and passage representations: sim(q(x), d(z)) = q(x)^T d(z).",
                    "We index 21 million 100-word passages from Wikipedia. We build an efficient Maximum Inner Product Search (MIPS) index "
                    "using FAISS to retrieve top-k passages with sub-second latency. During fine-tuning, the document index is kept fixed while "
                    "the query encoder and generator are updated jointly.",
                    "Evaluating on open-domain question answering benchmarks (Natural Questions, TriviaQA, WebQuestions), RAG models establish "
                    "new state-of-the-art results, generating more factual, specific, and diverse responses than parametric-only seq2seq baselines."
                ],
                True  # Page 3
            )
        ]
    )

    # 3. ICO-Cache Architecture Paper
    build_paper(
        os.path.join(output_dir, "ico_cache_architecture.pdf"),
        "ICO-Cache: Multi-Tiered Semantic Caching and Cost Isolation for LLM Systems",
        "ICO-Cache Research Team",
        "Serving Large Language Models (LLMs) in production is bottlenecked by inference latency and API costs. We present "
        "ICO-Cache, an open-source multi-tier caching architecture designed for enterprise RAG and conversational applications. "
        "ICO-Cache introduces a strict 7-layer cascade (L0 deterministic, L0b embedding, L1 exact, L2 semantic, L3 context-aware, "
        "L4 retrieval, and L5 prompt context) paired with deterministic corpus versioning, complete tenant isolation, "
        "and sub-millisecond decision tracing.",
        [
            (
                "1. Multi-Tier Cache Hierarchy",
                [
                    "Modern LLM architectures suffer from redundant computation across repeated queries, similar intents, and repeated "
                    "document retrieval. Existing semantic caches operate solely at the response level, failing when prompt contexts vary slightly. "
                    "ICO-Cache solves this by implementing an explicit hierarchy spanning every stage of generation:",
                    "Layer L0 provides deterministic function caching for static outputs and schemas. Layer L0b caches dense vector embeddings, "
                    "avoiding repeat calls to embedding models. Layer L1 performs exact hash matching on normalized prompts. "
                    "Layer L2 applies cosine similarity search in a vector store for semantic equivalence within a configurable threshold. "
                    "Layer L3 evaluates context-aware caching for conversational threads.",
                    "For RAG pipelines, Layer L4 caches retrieved document lists indexed by query hash, top-k, and corpus version. "
                    "Layer L5 caches assembled prompt contexts indexed by chunk content hashes, preventing duplicate context reconstruction."
                ],
                False
            ),
            (
                "2. Corpus Versioning and Cache Isolation",
                [
                    "A critical failure mode of RAG caching is stale document reuse: if a document in the corpus is updated or deleted, "
                    "retrieval caches must never serve invalid historical passages. ICO-Cache solves this through deterministic corpus versioning.",
                    "Every chunk in the corpus is fingerprinted by a SHA-256 content hash. The global corpus version is computed as a deterministic "
                    "digest over all sorted chunk hashes. The L4 retrieval cache key incorporates this corpus version: "
                    "l4:{tenant_id}:{query_hash}:{corpus_version}:{top_k}. If any document in the corpus changes, old corpus cache entries "
                    "are immediately isolated and never incorrectly reused.",
                    "Furthermore, multi-tenant isolation ensures tenant A can never read or overwrite cache entries belonging to tenant B."
                ],
                True  # Page 2
            ),
            (
                "3. Decision Tracing and Accounting",
                [
                    "To ensure observability and auditability in enterprise deployments, every request entering ICO-Cache produces an immutable "
                    "DecisionTrace. The decision trace records whether each layer (L0a, L0b, L1, L2, L3, L4, L5, LLM) was attempted, its outcome "
                    "(HIT, MISS, SKIPPED, BLOCKED), latency in milliseconds, and the exact reuse source.",
                    "Concurrently, the Token and Cost Accounting subsystem records input tokens, output tokens, tokens saved, cost, and dollars saved "
                    "using verified pricing models. Telemetry is streamed in real-time to the production monitoring dashboard."
                ],
                True  # Page 3
            )
        ]
    )


if __name__ == "__main__":
    generate_all_papers("examples/real-rag-demo/documents")
