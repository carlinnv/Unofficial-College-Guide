# The Unofficial Guide — Project 1

> **How to use this template:**
> Complete each section *after* you've built and tested the corresponding part of your system.
> Do not write placeholder text — if a section isn't done yet, leave it blank and come back.
> Every section below is required for submission. One-liners will not receive full credit.

---

## Domain

<!-- What topic or category of knowledge does your system cover?
     Why is this knowledge valuable, and why is it hard to find through official channels?
     Example: "Student reviews of CS professors at [university] — useful because official
     course descriptions don't reflect teaching style, exam difficulty, or workload." -->
The domain I chose was Computer Science course recommendations at the New Jersey Institute of Technology. This information may be hard to find on official channels because students are not given the opportunity to honestly review the classes they take on an official platform. It may also be hard to keep track of prerequisites and corequisites for certain classes because there is no official platform that does so for students. 

---

## Document Sources

<!-- List every source you collected documents from.
     Be specific: include URLs, subreddit names, forum thread titles, or file names.
     Aim for variety — sources that together cover different subtopics or perspectives. -->

| # | Source | Description | URL or location |
|---|--------|-------------|-----------------|
| 1 | Reddit | A thread in which the poster asks for 300-level electives. | https://www.reddit.com/r/NJTech/comments/1hjjoy9/cs_electives/ |
| 2 | Reddit | A thread in which the user asks for 300-level electives with the least workload. | https://www.reddit.com/r/NJTech/comments/tpyvgc/easiest_300_level_cs_electives/ |
| 3 | NJIT | A page that lists all of the Computer Science courses that can be taken at NJIT, including prerequisites for each course. | https://catalog.njit.edu/undergraduate/computing-sciences/computer-science/#coursestext |
| 4 | NJIT | A page that lists Informatics courses, many of which can be taken in conjunction with Computer Science. | https://catalog.njit.edu/undergraduate/computing-sciences/informatics/#coursestext | 
| 5 | NJIT | A page that shows an example schedule for a B.S. student in Computer Science. | https://catalog.njit.edu/undergraduate/computing-sciences/computer-science/bs/bs.pdf |
| 6 | Reddit | Poster requests advice on NJIT's CS graduate program and specific courses. | https://www.reddit.com/r/NJTech/comments/16jjtb3/advice_needed_regarding_njits_computer_science/ |
| 7 | College Class Reviews | The best and worst rated classes at NJIT. | https://collegeclassreviews.com/universities/new-jersey-institute-of-technology/top-courses |
| 8 | College Class Reviews | The hardest courses at NJIT, according to students. | https://collegeclassreviews.com/universities/new-jersey-institute-of-technology/rankings/hardest-courses |
| 9 | Reddit | Posters asks about the difficulty of CS courses at NJIT. | https://www.reddit.com/r/NJTech/comments/5hrikz/how_is_the_difficulty_of_some_of_the_cs_courses/ |
| 10 | NJIT | Latest news from the CS department at NJIT. | https://news.njit.edu/ |

---

## Chunking Strategy

<!-- Describe your chunking approach with enough specificity that someone else could reproduce it.
     Include:
     - Chunk size (characters or tokens) and why that size fits your documents
     - Overlap size and why (or why not) you used overlap
     - Any preprocessing you did before chunking (e.g., stripping HTML, removing headers)
     - What your final chunk count was across all documents -->

**Chunk size:**
600

**Overlap:**
100

**Why these choices fit your documents:**
After browsing through my documents, it seems like most of the NJIT pages contain information in chunks of 500-600 characters. The reviews are definitely shorter, but can be grouped with their replies in about 400-500 characters. I gave them a leeway of 100 characters because the reviews and course descriptions often vary up to 100 characters. 

**Final chunk count:**
238

---

## Embedding Model

<!-- Name the embedding model you used and explain your choice.
     Then answer: if you were deploying this system for real users and cost wasn't a constraint,
     what tradeoffs would you weigh in choosing a different model?
     Consider: context length limits, multilingual support, accuracy on domain-specific text,
     latency, and local vs. API-hosted. -->

**Model used:**
I am going to use all-MiniLM-L6-v2 via sentence-transformers.

**Production tradeoff reflection:**
If there were no constraints in this project, I would choose an embedding model that offers multilingual support due to NJIT's large international student population. 

---

## Grounded Generation

<!-- Explain how your system enforces grounding — how does it prevent the LLM from answering
     beyond the retrieved documents?
     Describe both your system prompt (what instruction you gave the model) and any structural
     choices (e.g., how you formatted the context, whether you filtered low-relevance chunks).
     Do not just say "I told it to use the documents" — show the actual instruction or explain
     the mechanism. -->

**System prompt grounding instruction:**

Grounding is enforced via the system response and a structural "gate".

The system prompt at the top of `main.py` tells the model it can only answer with the numbered/labeled sources passed in the user message. I specified that it can only use information from the provided sources, every factual claim must be cited inline, and the model must reply with a refusal sentence if the sources do not contain the information required to answer. It is also not allowed to make up facts (hallucinate). 

Two structural choices enforce grounding: 
1) **Low-relevance filtering / refusal gate:** The model will drop retrieved chunks below a cosine-similarity threshold of 0.20. If no chunk clears the threshold, the system returns the refusal sentence without calling the LLM.
2) **Context formatting:** each chunk is presented prefixed with its exact citation label `[Source Name, URL]`, so the model can only cite sources that were actually retrieved. Inlcuding the URL also differentiates between sources that share a name (e.g. multiple Reddit threads, multiple NJIT pages).

**How source attribution is surfaced in the response:**

In the response, I made sure to instruct the model to include inline citations in the form [Source Name, URL]. 

---

## Evaluation Report

<!-- Run your 5 test questions from planning.md through your system and record the results.
     Be honest — a partially accurate or inaccurate result that you explain well is more
     valuable than a suspiciously perfect result. -->

| # | Question | Expected answer |
|---|----------|-----------------|
| 1 | Which CS class at NJIT is most commonly rated among one of the hardest? | CS 350 | CS 350 | Relevant | Very accurate
| 2 | Which CS professor at NJIT is most commonly rated among the worst? | Professor Bassel | Not enough information to respond | Off-target | Inaccurate
| 3 | Which CS professor at NJIT do students enjoy taking? | Professor Dale | Not enough information to respond | Off-target | Inaccurate
| 4 | What are the prerequisites of CS 288? | CS 280 and CS 100 | None of the sources state a prerequisite. However, many sources say that CS 288 is a tough class to take. | Partially relevant | Partially accurate 
| 5 | What is an easy CS elective to take at NJIT? | CS 485 | CS 375, CS 485 | Relevant | Accurate

**Retrieval quality:** Relevant / Partially relevant / Off-target  
**Response accuracy:** Accurate / Partially accurate / Inaccurate

---

## Failure Case Analysis

<!-- Identify at least one question where retrieval or generation did not work as expected.
     Write a specific explanation of *why* it failed, tied to a part of the pipeline.

     "The answer was wrong" is not an explanation.

     "The relevant information was split across a chunk boundary, so retrieval returned
     only half the context — the model didn't have enough to answer correctly" is an explanation.

     "The embedding model treated the professor's nickname as out-of-vocabulary and returned
     results from an unrelated review" is an explanation. -->

**Question that failed:**
"What are the prerequisites of CS 288?" (expected: CS 280 and CS 100).

**What the system returned:**
The system did not state the prerequisites. It returned that none of the sources list a prerequisite for CS 288, and instead surfaced student comments about CS 288 being a difficult course. The correct prerequisites were never produced, even though the NJIT catalog page (source 3) was collected and does contain them.

**Root cause (tied to a specific pipeline stage):**
This is a **chunking-stage** failure. The catalog's CS 288 entry was split across a 600-character chunk boundary, so the course header ("CS 288 ...") landed in one chunk and its "Prerequisite: CS 100 and CS 280" line landed in the next. I confirmed this by searching the stored chunks: the string "CS 288" appears in source 3 across the full document, but no single stored chunk contains "CS 288" together with its prerequisite text. Because retrieval returns whole chunks, the prerequisite line was never retrieved alongside the course code, so the model had no grounded way to connect them. The grounding gate then did its job correctly — it refused rather than guess — which means the wrong answer here is a retrieval/chunking limitation, not a hallucination. This is exactly the "chunks might split key information" risk I named in planning.md.

**What you would change to fix it:**
I would switch the catalog pages to **structure-aware chunking** that splits on course-entry boundaries (one chunk per course), so each course code stays attached to its prerequisites and description. As a lighter-weight alternative I could increase the chunk size (or overlap) specifically for the catalog sources, or raise top-k so adjacent header/prerequisite chunks are more likely to be retrieved together. Structure-aware chunking is the most direct fix because the catalog is already cleanly delimited by course entries.

---

## Spec Reflection

<!-- Reflect on how planning.md shaped your implementation.
     Answer both questions with at least 2–3 sentences each. -->

**One way the spec helped you during implementation:**
The Retrieval Approach section and the Architecture diagram named the exact components I needed — all-MiniLM-L6-v2 via sentence-transformers, ChromaDB as the vector store, top-k = 4, and cosine similarity — which made the embedding and retrieval code almost mechanical to build. Because the spec was concrete, I could direct the AI tool to implement each stage without ambiguity, and I could check the output against a fixed target instead of guessing what "good" looked like. The diagram also made the boundaries between stages clear, so I knew the embedding step's only job was to load chunks, embed them, and store them — nothing more.

**One way your implementation diverged from the spec, and why:**
The spec described retrieval as simply "top-k = 4, cosine similarity," but the implementation added two things that weren't in the plan: a relevance threshold that drops low-similarity chunks (and refuses to answer if none clear it, without calling the LLM), and a programmatic source list built from chunk metadata rather than trusting the model to cite. I added these because grounding turned out to need structural enforcement, not just a prompt instruction — without the threshold gate, off-topic questions would still pass four weak chunks to the model and invite a hallucinated answer. I also changed the inline citation format from a plain source number to `[Source Name, URL]` so each citation is self-contained and readable in the response.

---

## AI Usage

<!-- Describe at least 2 specific instances where you used an AI tool during this project.
     For each: what did you give the AI as input, what did it produce, and what did you
     change, override, or direct differently?

     "I used Claude to help me code" is not sufficient.
     "I gave Claude my Chunking Strategy section from planning.md and asked it to implement
     chunk_text(). It returned a function using a fixed character split. I overrode the
     chunk size from 500 to 200 because my documents are short reviews, not long guides." -->

**Instance 1**

- *What I gave the AI:* My Retrieval Approach section and the Architecture diagram from planning.md, plus the requirement to use sentence-transformers (all-MiniLM-L6-v2) and ChromaDB. I asked it to implement the embedding step — load the chunks from `chunk_documents.py`, embed them, and store them.
- *What it produced:* `retrieval.py`, which loads and chunks the documents, embeds each chunk with all-MiniLM-L6-v2, and upserts them into a persistent ChromaDB collection configured for cosine similarity, plus a `retrieve()` function that returns the top-4 chunks for a query.
- *What I changed or overrode:* I had it persist the store to disk (`chroma_db/`) instead of an in-memory client so the embeddings survive between the embedding and generation steps, and I had it normalize embeddings so cosine behaves consistently. I then directed it to populate the full store across all 10 sources, which produced the final chunk count.

**Instance 2**

- *What I gave the AI:* The Architecture diagram and Evaluation Plan, plus my grounding requirements: answers must come only from retrieved context with source attribution, the output should be an answer plus a source list, and I wanted a Gradio interface.
- *What it produced:* `main.py`, which retrieves the top-4 chunks, sends them to a Groq LLM (llama-3.3-70b-versatile) with a grounding system prompt, and returns the answer with a source list, exposed through both a CLI and a Gradio app.
- *What I changed or overrode:* I directed it to make grounding *structural* rather than just a prompt request — adding the relevance gate that refuses without calling the LLM, and building the source list in code from metadata so attribution can't be dropped by the model. I also overrode the citation format to `[Source Name, URL]` so citations are readable inline. Testing against my Evaluation Plan is what surfaced the CS 288 chunking failure documented above.

## Demo Video
[![Demo Video](https://www.loom.com/share/03f69c5ef3a042a882ead97c7930add9)](https://www.loom.com/share/03f69c5ef3a042a882ead97c7930add9)