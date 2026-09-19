# Architecture

## Runtime boundaries

```mermaid
flowchart TD
    UI[Streamlit / CLI] --> Service[StudyService]
    UI --> Jobs[SQLite JobManager]
    Jobs --> Service
    Service --> Retriever[LocalRetriever]
    Service --> Provider[CodexProvider]
    Provider --> CLI[Official codex exec]
    Retriever --> E5[Local E5 + BM25]
    UI --> Repository[Progress / Learning repositories]
```

`src/service.py` owns typed `LearningRequest`/`LearningOptions`, input limits, context selection, task prompts, schemas and domain rules. `src/schemas.py` owns strict JSON Schema and result validation. UI does not import subprocess or any model API client. RAGCore/AITutor are compatibility facades over the Service and share retrieval; they no longer pass OpenAI clients or embed inside tutor methods. `main.py` also queues through the same Service/Provider and process lock.

`src/runtime.py` creates resources without invoking a model, logging in, loading local weights or indexing PDFs. Dashboard/history need only repositories; Library enumerates local material metadata. Retrieval/model loading happens on explicit index/search/learning actions. Diagnostics do not generate.

## Learning experience and saved choices

The five Streamlit screens remain Dashboard, RAG, Feynman Drill, Curriculum and Library. Their navigation labels describe the learning activity: today's learning, content consultation, tests/review, courses/lessons and the material library. Dashboard links to PDF registration, course creation, saved courses and due weaknesses; navigation callbacks queue the destination before keyed Streamlit widgets are instantiated. These links and question starters do not start generation.

`LearningOptions` preserves its previous fields and adds a learning goal, prior knowledge, learning approach, analogy domain and session duration. Goal/prior-knowledge text is limited to 1,200 characters each; analogy preferences to 300. The four approaches are systematic understanding, worked examples, practical projects and exam preparation. Session duration is one of 15, 25, 45 or 60 minutes. Old serialized options load with defaults. `PROMPT_VERSION` is `study-3`; the generated JSON contracts retain `SCHEMA_VERSION=study-2`.

`views/learning_profile.py` saves a profile per subject in `learning.sqlite3`. A profile saved before selecting a subject supplies the default for subjects without their own saved profile. Invalid saved settings are preserved and produce a warning. A new course stores the complete request options and material revision in its progress metadata. Later changes to the profile affect new courses and general consultation, while an existing course keeps its creation settings for lectures, dialogue and assessment. The learner may select the course exam difficulty explicitly; grading retains that exam's difficulty. Legacy courses without saved settings continue to use current options.

The Service translates these choices into task-specific instructions: learning outcomes and prerequisite order for curricula; reasoning, worked examples, guided practice, independent checks and review for lectures; focused hints/examples for dialogue; aligned questions and actionable feedback for assessment. Analogy instructions require both the correspondence and its limits. A concise lecture still needs these learning stages. Preferences are data inside the same untrusted JSON object as material and answers, and cannot redefine tool, source, schema or grading rules. Every result includes an application-owned options snapshot. Prompt structure is an implementation contract, not proof of educational effectiveness.

Course pages expose a roadmap and reading, discussion and assessment tabs. Completed chapters remain available for review; next-chapter navigation does not grant progress by itself. RAG and lecture discussion retain drafts by subject/session and, for a lecture, course/chapter/lecture ID. Question starters append to the draft and leave submission explicit. Course notes and RAG conversations can be exported as Markdown.

## Generation and privacy

The Provider uses the integrity-verified official CLI 0.155.1 at a dedicated absolute path, model `gpt-6-astra` and effort `medium`, argv plus stdin, `shell=False`, ephemeral per-request workdir, `--json`, `--output-schema`, `--sandbox read-only`, `--ignore-user-config`, strict configuration and tool-disable settings. No user-supplied shell command or arbitrary flag exists in the UI. Environment allowlisting excludes API keys, endpoint overrides and proxies. Authentication and refresh belong to the CLI; no Python code reads tokens/auth JSON.

The default executable is `~/.local/share/study-with-ai/tools/codex/0.155.1/vendor/aarch64-apple-darwin/bin/codex`. The application owns a separate `~/.local/share/study-with-ai/codex-home`, mode 0700, with an ownership marker. Setup refuses to adopt an unrelated existing directory. Login, login status, model catalog and generation use this home with `cli_auth_credentials_store="file"`, `forced_login_method="chatgpt"` and the built-in `openai` provider. Shared Codex credentials and configuration are not copied or changed. Local administrator path overrides do not bypass the version/hash/home checks.

`read-only` alone is not a confidentiality boundary. The audited settings provide **tools=[]** in a synthetic localhost wire probe. Synthetic markers cover shared/project AGENTS, shared/dedicated/project configuration, skills, hooks, MCP, plugins and history to test context contamination and startup side effects. The dedicated home is outside the synthetic shared HOME. The new 0.155.1 probe observed no marker injection or hook/MCP execution; the request fixed the required model/effort and did not inherit Fast service tier. This is mock wire evidence, not a real model result.

Before generation, the same official binary runs a short-lived stdio app-server only for read-only `config/read`, `configRequirements/read` and paginated `model/list`. No thread or turn is started. The Provider verifies effective authentication, model, effort, sandbox, disabled tools/features, instruction sources, MCP, endpoints and service tier. Unexpected managed/organization policies fail closed for review and are never disabled. Effective settings are rechecked after authentication; CLI-managed catalog listing and account entitlement remain separate claims. Generation still runs through `codex exec`; no MCP service or replacement application framework is added.

Current authentication, generation outcomes and execution limits are recorded in [CODEX_BOUNDARY](CODEX_BOUNDARY.md) and [TEST_REPORT](TEST_REPORT.md), rather than inferred from model catalog availability. Phase 1's 0.152.1 findings remain historical evidence. The fixed CLI and authentication contracts are documented in the [CLI audit](PHASE2_CLI_AUDIT.md) and [authentication/retry audit](PHASE2_AUTH_RETRY_AUDIT.md).

Prompts use a single serialized untrusted-data object for excerpts, answers and history. App-owned developer instructions explicitly forbid following embedded instructions. These instructions complement tool isolation; they do not establish semantic prompt-injection immunity. Fake-provider testing does not prove that a real model will always grade correctly.

Generation sees bounded PDF excerpts: maximum 10 chunks, 10,000 characters total and 1,600 per chunk, plus at most 20 history entries from the current material revision. Ordinary questions use query retrieval. Curriculum creation uses balanced representative context across PDFs/pages. RAG's explicit overview selection uses the same representative selector; a normal query with no matches does not silently become an overview. Application-owned `context_coverage` records indexed/selected scope and the smaller context actually supplied to the Provider. Representative excerpts are not a claim of full PDF coverage.

Saved lecture text and the context sent with a later question/exam are separate. `src/lecture_context.py` accepts the saved main text (up to 40,000 characters) and general supplement (up to 20,000), retaining short content in full or selecting bounded passages from longer content: opening, ending, relevant passages and spread across the remaining sections. Both fields share a 6,000-character context cap, including range labels and explicit main/supplement labels. The allocation preserves both substantial fields and gives more space to the one relevant to the learner's question. Original character ranges, field names and an excerpt flag make the selection inspectable; it is not a generated summary. Stored lecture text remains intact, and the supplement never becomes a material quotation. Non-lecture input is checked against 48,000 UTF-8 bytes before selection, then the full payload is checked again after inserting the excerpts. The Provider's 64 KiB final prompt limit remains independent. New answer/dialogue history also retains the displayed supplement in its assistant content with an explicit general-supplement heading, so a question posed there survives into the next turn; existing history is not rewritten. See [LOCAL_RETRIEVAL](LOCAL_RETRIEVAL.md) for selection and coverage details. No whole home/repo/material collection is a working root. Returned source IDs must be in the offered set; reference validity is not proof that every factual statement is supported.

Result Markdown uses safe Streamlit defaults. Simple Mermaid flowcharts are parsed to an allowlisted node/edge data structure and rendered with Graphviz. HTML, links, directives and unsupported diagrams are code text; generated code is never executed.

## Jobs, idempotency and cancellation

`JobManager` stores requests, states, results and sanitized errors in private SQLite. The lifecycle is queued → running → succeeded/failed/cancelled; recovered unfinished work becomes interrupted. The queue is process-local for callables and durable for state; restart never silently replays a request. Concurrency is one per shared state directory, including multiple server processes, enforced by an OS lock. The lock descriptor is inherited by the owned CLI child so a killed parent cannot release the slot prematurely. The worker polls cancellation and never manipulates Streamlit state.

`LearningRepository.claim_submission()` serializes pending check / job registration / pointer save for the same scope. The request digest contains subject, session, course, textbook revision, model/effort, prompt/schema versions, options and payload. Separate attempts and deliberate retries get new IDs. Reading a completed job does not generate again. Results persist with job receipt IDs; progress events independently deduplicate XP/weakness changes. A completed result for a different subject/session/course cannot be applied.

`views/common.py:render_pending` is a Streamlit fragment with a two-second refresh interval. It polls existing job state, offers cancellation and applies terminal success through the existing receipts; it never submits work. After applying a result it clears only the observed pending pointer and requests a full rerun so the surrounding lesson/assessment updates. Fragment refreshes do not bypass scope claims or progress deduplication. Synthetic AppTest checks exercise refresh/rerun behavior; browser timer behavior is a separate UI validation surface.

Exam drafts are stored under the attempt ID. An unfinished exam with a draft requires confirmation before replacement. `LearningRepository.reset_exam()` holds the same SQLite write lock used by submission claims while comparing the expected attempt, checking active/succeeded pending work, archiving public questions and the draft, and clearing the current quiz/grade. Stale tabs cannot clear a newer attempt, and an active grade blocks reset. Archived ungraded attempts never expose model answers/rubrics; original drafts and progress grading history remain stored. Drafts, archival and profile fields use the existing document schema without a database-version change.

Provider drains stdout and stderr concurrently, enforces byte/time limits, rejects invalid/truncated JSONL and requires both a completed turn and final message. Intermediate reasoning/events are neither exposed to users nor stored as answers. Cancel/timeout terminates only its newly owned process group and reaps it. Cancelled results are discarded before job success. Application automatic retries are zero. The Phase 2 contract permits finite CLI retries: built-in HTTP retry defaults to 4 and stream retry to 5, while `unbounded_connection_retries=false` is explicitly set and verified. Transport switching and authentication recovery mean these per-loop values do not establish a total HTTP or inference count per job. The application deadline and cancellation still bound the owned process. Actual internal attempts and server inference counts are unknown; a single application job is not reported as a single service request or unit of usage.

A new material revision invalidates an in-flight result: Service compares revisions before/after retrieval and before/after generation, and UI checks again before application. A filesystem change in the tiny interval after the last check is still possible; there is no transaction spanning arbitrary external PDF edits and SQLite. Stored source IDs/versions preserve which snapshot was used. Course lecture updates patch the current chapter inside the progress transaction to avoid replacing another tab's whole curriculum.

Lecture writes compare the previous lecture ID inside that transaction, so an older job cannot overwrite another session's newer lecture. Course exams and grades carry app-owned chapter index and lecture ID. Chapter completion verifies the passed attempt against that exact chapter, current stored lecture and current material revision before granting 50 XP once. Results rejected after material/lecture changes can be explicitly discarded without being treated as successful learning.

## Repositories and retrieval

- `progress.sqlite3`: versioned progress document, lossless legacy migration, unknown fields, event ledger, migration provenance.
- `learning.sqlite3`: scoped profiles, messages, results, context choices, drafts and attempt archives; atomic pending claim/reset and result receipts.
- `jobs.sqlite3`: request lifecycle, validated results, request digest and metadata. Payload/result are private learning data; diagnostics return metadata only.

SQLite files are private, WAL-enabled, version checked, and protected against parallel initialization. Unknown future versions and corrupt files fail closed. The old `progress.json` remains unchanged. Secrets/materials/models/caches/databases are not committed.

Retriever owns safe category/subject paths, PDF extraction, stable material/chunk provenance, local E5 and Japanese-aware BM25, snapshot cache identity and shape validation. `course_context()` reuses that index/ranker while balancing document and page coverage; it introduces no extra model request or embedding API. See [LOCAL_RETRIEVAL](LOCAL_RETRIEVAL.md).

Library versions are captured once per Retriever/Embedder instance, using an independent search-path snapshot for package discovery. This avoids false revision changes when Streamlit mutates `sys.path` during reruns. Restart the app after changing installed dependencies; do not mutate a running environment in place.

## Synthetic live validation and quality review

`scripts/live_e2e.py` separates read-only `--check-only` from opt-in `--run --confirm-live`. Its fixed, owned workspace is `.study-runtime/phase2-live`; arbitrary data/state/cache environment overrides cannot redirect it to personal materials. It creates a synthetic bilingual learning note and uses private synthetic databases. A durable reservation ledger permits seven ordered operations (minimal probe, answer, curriculum, lecture, dialogue, quiz, grade) plus one explicitly justified reserve operation, at most eight application jobs across restarts. Failures and interruptions retain their reservations. Completed results are reused and progress receipts prevent duplicate credit; no automatic retry or replay occurs.

The grading input intentionally combines reference answers with one explicit misconception. The report checks that this wrong item loses points, without presenting this as an independent grading benchmark. Result schemas, source IDs and technical completion do not establish educational quality. The generated review template requires concrete evidence for source support, lecture/dialogue relevance, question alignment, partial-error grading, reasoning, citations/pages and restart/progress behavior. Only a manual review bound to the current result digest can record quality acceptance. Execution outcomes, completed review evidence and outstanding limits are maintained in [TEST_REPORT](TEST_REPORT.md).
