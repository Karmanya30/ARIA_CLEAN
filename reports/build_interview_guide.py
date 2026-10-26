"""Generate the source-reviewed ARIA interview guide without calling live services."""
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Flowable

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'ARIA_Interview_Data_Pipeline_and_Architecture.pdf'
INK = colors.HexColor('#172b46')
BLUE = colors.HexColor('#175c80')
LIGHT = colors.HexColor('#edf4f8')
styles = getSampleStyleSheet()
styles.add(ParagraphStyle('BodyA', fontName='Helvetica', fontSize=10, leading=14, spaceAfter=8, textColor=INK))
styles.add(ParagraphStyle('SmallA', parent=styles['BodyA'], fontSize=8, leading=11))
styles.add(ParagraphStyle('TitleA', fontName='Helvetica-Bold', fontSize=28, leading=33, textColor=INK, spaceAfter=18))
styles.add(ParagraphStyle('HeadingA', fontName='Helvetica-Bold', fontSize=19, leading=24, textColor=INK, spaceAfter=14))
styles.add(ParagraphStyle('SubA', fontName='Helvetica-Bold', fontSize=11.5, leading=15, textColor=BLUE, spaceBefore=9, spaceAfter=6))
styles.add(ParagraphStyle('CodeA', fontName='Courier', fontSize=8, leading=11, spaceAfter=8, textColor=INK))
story = []
source_text = []

def p(s, style='BodyA'):
    story.append(Paragraph(s, styles[style]))
    source_text.append(s)

def h(s): p(s, 'SubA')
def bullet(s): p('&#8226; ' + s)
def page(title, kicker):
    if story: story.append(PageBreak())
    p(kicker.upper(), 'SmallA')
    p(title, 'HeadingA')

def table(headers, rows, widths):
    data = [[Paragraph(escape(str(c)), styles['SmallA']) for c in r] for r in [headers]+rows]
    t = Table(data, colWidths=widths, repeatRows=1, hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#d9e8f1')),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,LIGHT]),
        ('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#cad6df')),
        ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
        ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
    story.append(t)
    source_text.append(str([headers]+rows))

class Pipeline(Flowable):
    def __init__(self, boxes):
        super().__init__(); self.boxes=boxes; self.width=491; self.height=len(boxes)*57-10
    def draw(self):
        c=self.canv
        for i,(title,detail) in enumerate(self.boxes):
            y=self.height-(i+1)*57+10
            c.setFillColor(LIGHT); c.setStrokeColor(colors.HexColor('#9db9cc'))
            c.roundRect(0,y,491,45,6,fill=1,stroke=1)
            c.setFillColor(INK); c.setFont('Helvetica-Bold',10); c.drawCentredString(245,y+28,title)
            c.setFont('Helvetica',8); c.drawCentredString(245,y+13,detail)
            if i<len(self.boxes)-1:
                c.setStrokeColor(BLUE); c.line(245,y,245,y-10); c.line(242,y-7,245,y-10); c.line(248,y-7,245,y-10)

page('ARIA: Data Pipeline & Project Architecture', 'Interview preparation | 24 October 2026')
p('Explain the system clearly.<br/>Trace the data end to end.<br/>Defend the design decisions.', 'TitleA')
p('A repository-based guide to ARIA, the AI-powered personal finance assistant, financial tutor, market analyst and equity researcher.')
h('Start here if your interview is soon')
bullet('<b>10 minutes:</b> Read pages 2-3, the equity pipeline on page 9, and the answer bank on page 14.')
bullet('<b>30 minutes:</b> Add the shared pipeline, statement ingestion, model training and validation pages.')
bullet('<b>For a deep technical round:</b> Review all pages, then practise drawing the diagram from memory.')
h('Scope and evidence')
p('Prepared from the current files in E:/ARIA. This guide describes source-code behavior; it does not assert that every optional model, provider, account integration or GPU service is installed or running. No live market requests, model training or full application tests were performed to prepare this document.')
p('Older project reports describe a Streamlit prototype. The current application uses React + TypeScript and FastAPI. This guide prioritizes the current implementation. Proposed scaling work is explicitly marked as a future design.')
p('<b>Use in the interview:</b> Replace ownership statements with the parts you personally built. Do not claim deployment scale, accuracy or latency that you have not measured.')

page('The project in 90 seconds', '02 | Project overview')
p('<b>Suggested explanation:</b> "ARIA brings four finance-related workflows into one conversational interface. A React frontend calls a FastAPI backend. Every question goes through a shared pipeline that normalizes the text, binds the user and conversation context, routes to a domain module, checks grounding and prepares the response for text or voice. Personal-finance calculations and equity valuations are computed in Python; language models mainly explain the results. SQLite stores user state and reports, while FAISS supports semantic concept retrieval. Optional voice and avatar services reuse the same answer path."')
table(['Module','Core job','Main techniques'],[
    ['Personal finance','Profile-aware planning, spending, risk and budgeting','Deterministic engine; XGBoost; LSTM; Isolation Forest; LP'],
    ['Financial tutor','Concept explanations, quizzes and adaptive teaching','Sentence-BERT + FAISS; LSTM knowledge tracing; DQN'],
    ['Market analysis','Quotes, indices, instrument information and news','External market data; aggregation; LLM explanation'],
    ['Equity research','Statements, ratios, valuation and saved research','Deterministic analysis; evidence ledger; narrative audit']
], [95,180,216])
h('The central design decision')
p('Keep structured data and numerical computation separate from natural-language presentation. An LLM response is not the source of truth for a price, ratio, financial profile or valuation. Source coverage and guard strength vary by route; they do not provide a universal factual guarantee.')
h('Three pipelines to distinguish')
bullet('<b>Online serving:</b> a question becomes a contextual, grounded answer.')
bullet('<b>Data ingestion:</b> files, quotes, statements, concepts and headlines become validated structured records.')
bullet('<b>Offline learning and validation:</b> generated datasets or historical data produce model artifacts, backtests and measured evidence.')

page('System architecture', '03 | Draw this in the interview')
story.append(Pipeline([
    ('React + TypeScript UI', 'Chat, profile, learning progress, markets, research, voice and avatars'),
    ('FastAPI API adapters', 'Authentication, input schemas, resource limits, HTTP / WebSocket routes'),
    ('Shared question pipeline: modules/qa/pipeline.py', 'Understand -> context -> route / answer -> trust -> persist -> present'),
    ('Domain modules', 'Personal finance | Tutor | Markets | Equity research'),
    ('Shared infrastructure', 'Owner-scoped state | Memory | LLM client | News | Company resolution'),
    ('Storage and external providers', 'SQLite | FAISS | Local artifacts / Parquet | Market data | LLM APIs')
]))
story.append(Spacer(1,12))
p('The arrows summarize dependencies. Data providers feed the domain modules; persistence is shared infrastructure rather than a mandatory final step of every provider call.', 'SmallA')
h('Deployment topology')
p('Development normally runs Vite on port 5173 and FastAPI on port 8000, with browser requests proxied to the API. The backend is a modular monolith: domain packages share one core application rather than independently deployed microservices. Optional avatar services run separately; forecast validation jobs can spawn isolated child processes.')
p('<b>Why this shape?</b> It keeps a student-scale application easy to run and lets all channels reuse the same logic. The costs are shared process resources, tight deployment coupling and state that needs extra work before horizontal scaling.')
p('<b>Sources:</b> api/main.py; web/package.json; modules/qa/pipeline.py; modules/equity_research/forecast/jobs.py.', 'SmallA')

page('One question, end to end', '04 | Online serving pipeline')
table(['Stage','What happens','Relevant source'],[
 ['1. Receive','The API creates a typed QARequest with query, owner, session, mode, channel, optional focus and request_id.','api/routes/chat.py; modules/qa/models.py'],
 ['2. Understand','Normalize spelling, text-speak and Hinglish. The orchestrator handles dialogue, domain and crisis-related behavior.','shared/understand.py; core/orchestrator.py'],
 ['3. Bind context','Set the current owner; verify conversation ownership; resolve focused instruments; attach memory and profile context.','modules/qa/pipeline.py; modules/qa/focus.py'],
 ['4. Execute a turn','Archive the request, lock the session and replay a completed retry when request_id matches.','core/session.py; shared/conversation_memory.py'],
 ['5. Route and compute','Resolve intent, company and page focus; run the relevant domain pipeline.','core/router.py; core/orchestrator.py'],
 ['6. Check trust','Apply route-specific grounding checks, disclosures and degraded-response handling.','modules/qa/trust.py'],
 ['7. Present and save','Prepare spoken/audio presentation where needed; complete the turn and checkpoint state.','modules/qa/present.py; core/session.py']
], [78,274,139])
h('Follow-up example')
p('A user requests research on TCS and then asks, "What about its debt?" Conversation memory and company focus help resolve the reference. The system should use the resolved company and fetched statements rather than answering with an isolated generic definition of debt.')
h('Retry behavior')
p('A successful repeated request_id can return the saved response. Reusing the id for a different message is an error. This is request-level replay, not a promise of exactly-once execution across every external side effect or deployment topology.')
p('<b>Observability:</b> qa.answer logs channel, mode, route, correction, grounding, degradation and stage timings. total_ms captured in response metadata and the final log timer can differ because they are sampled at different points.')

page('Data ingestion and statement imports', '05 | The user-data pipeline')
story.append(Pipeline([
 ('Upload a statement or transaction file', 'CSV / TSV / text / Excel / text-extractable PDF / JSON / OFX'),
 ('Parse, normalize and validate', 'Dates -> ISO | Amounts -> numeric | Debit / credit -> direction | Categories -> common keys'),
 ('Create an owner-scoped durable preview', 'Parsed rows, suggested profile values, warnings and expiry in SQLite'),
 ('Import the reviewed preview', 'Check ownership and expiry; deduplicate; optionally apply profile suggestions'),
 ('Commit atomically', 'Transactions + optional profile changes + import receipt in one database transaction')
]))
story.append(Spacer(1,10))
h('Canonical transaction contract')
p('The parser emits date, merchant, positive amount, debit/credit direction and category. The storage mapping translates profile categories such as rent to housing and health to medical. Credits and expenses must remain distinct so income is not counted as spending.')
h('Why preview and atomic import matter')
p('A preview exposes parsing problems before persistence. The import stores a receipt and reuses it on retries. SQLite writer serialization protects deduplication across overlapping previews and processes. A failed transaction should not leave only half the profile or transaction changes saved.')
h('Quality controls and limits')
p('The parser bounds rows, spreadsheet expansion, archive members, sheet count, cell count and PDF processing. Unsupported or ambiguous inputs produce warnings or errors. Do not describe this as a general OCR pipeline: image-only scans need a separate extraction capability.')
p('<b>Sources:</b> modules/finance/statement_import.py; shared/statement_store.py; shared/user_store.py; tests/finance/test_statement_durability.py.', 'SmallA')

page('Personal-finance inference', '06 | From profile to computed advice')
p('<b>Inputs:</b> facts supplied in chat or the profile wizard, persisted transactions, income, age, dependents, EMI, assets, liabilities, goals and other known profile fields. Stored defaults are not necessarily user-confirmed facts; sources metadata tracks what is actually known.')
h('Two complementary computation paths')
p('<b>Profile-aware deterministic engine:</b> computes net worth, financial-health components, goal funding, affordability, retirement/FIRE and what-if results from available facts. When a required fact is missing, the finance flow can ask a specific clarification.')
p('<b>Model orchestration:</b> the structured finance orchestrator combines risk classification, spending forecasts, anomalies, constrained budgeting, tax computation and SIP allocation before asking the shared language-model client for narration.')
table(['Component','Input and transformation','Output'],[
 ['XGBoost risk','Log income, age, dependents, debt/income, category ratios, volatility, channel shares and more','Risk class, confidence, SHAP factors'],
 ['Spending LSTM','Monthly category spending / income; sequential context','Three-month category forecasts with P10/P50/P90 heads'],
 ['Isolation Forest','Transaction-derived anomaly features','Unusual-transaction flags; not proof of fraud'],
 ['Budget optimization','Income, fixed obligations, risk and constraints','Feasible category allocation or handled infeasibility'],
 ['Deterministic tools','Explicit profile inputs and configured assumptions','SIP/EMI calculations, planning and tax outputs']
], [100,246,145])
h('Illustrative example, not a measured result')
p('For monthly income Rs. 100,000 and EMI Rs. 15,000, debt-to-income is 0.15. This value is a feature, not the complete risk decision. The system should derive the remaining features from the user\'s actual history rather than inventing transactions.')
p('<b>Sources:</b> modules/finance/pipeline.py; personal.py; engine.py; orchestrator.py; features.py; forecast_model.py.', 'SmallA')

page('Offline training and model artifacts', '07 | Training is separate from serving')
table(['Pipeline','Data / preparation','Artifact or serving role'],[
 ['Risk training','Persona-conditioned synthetic household profiles and transactions; shared feature builder','XGBoost JSON and auxiliary artifacts'],
 ['Spend training','Monthly category ratios and sequence windows; context versus future targets','PyTorch LSTM checkpoint'],
 ['Tutor index build','Concept texts and metadata -> normalized Sentence-BERT embeddings','FAISS index.faiss + meta.json'],
 ['Knowledge tracing','Generated concept / correctness sequences','LSTM knowledge-tracing checkpoint'],
 ['Teaching policy','Training environment representing mastery and teaching decisions','DQN policy ZIP']
], [105,240,146])
h('Rebuild sequence from the repository')
for command in [
 'python -m scripts.generate_synthetic_transactions',
 'python -m modules.finance.train.train_xgb_risk',
 'python -m modules.finance.train.train_lstm_spend',
 'python -m scripts.build_concept_kb',
 'python -m scripts.generate_kt_sequences',
 'python -m modules.tutor.train.train_lstm_kt',
 'python -m modules.tutor.train.train_dqn_teacher']:
    p(escape(command),'CodeA')
h('How to defend the data choice')
p('Synthetic data makes controlled experiments possible without collecting sensitive household histories. It also creates a substantial realism limit: a classifier can learn the generator\'s personas, and good synthetic performance does not establish real-world suitability. DQN rewards in a simulator do not establish improved student learning.')
h('Evaluation points to discuss')
p('For a future stronger evaluation, hold out users for risk classification, use chronological splits for forecasting, fit preprocessing inside the training fold, and compare against simple baselines. Report macro-F1 / calibration for classification, MAE / quantile loss / interval coverage for forecasts, and independently measured learning gains for tutoring. These are evaluation proposals, not scores measured for this PDF.')
p('<b>Artifacts:</b> models/finance/, models/tutor/, data/vector_store/. Model/data roots are configurable through config/paths.py.', 'SmallA')

page('Adaptive tutor and semantic retrieval', '08 | Retrieval + mastery + teaching policy')
story.append(Pipeline([
 ('Question -> Sentence-BERT embedding', 'Encode with the same model used for the concept index'),
 ('FAISS concept search and confidence gating', 'Normalized vectors + inner product implement cosine similarity'),
 ('Load learner history -> estimate mastery', 'LSTM knowledge tracing uses concept / correctness interactions'),
 ('Select a teaching action with DQN', 'Target mastery, prerequisite mastery, recent accuracy, session length, difficulty'),
 ('Explain -> optional quiz -> persist learning', 'Cognitive / Functional / Causal explanation; update after a quiz answer')
]))
story.append(Spacer(1,10))
h('What makes this retrieval-based?')
p('The retriever returns concept metadata from a curated finance knowledge base. It is semantic concept retrieval rather than unrestricted search over the internet. Low-confidence matches are rejected; the tutor pipeline can fall back to a conversational LLM response when no concept or local resource is available.')
h('Similarity equation')
p('For normalized vectors q and d: similarity = q dot d = cosine(q, d). FAISS IndexFlatIP performs exact inner-product search over stored vectors. The current small concept collection does not require a distributed vector database.')
h('Adaptive behavior')
p('The orchestration maps estimated mastery to explanation depth. The policy can choose a teaching action and request a quiz. Recording a quiz answer appends a correctness interaction, recomputes mastery and saves the learning state for later turns. A mastery probability is a model estimate, not a certified assessment of competence.')
p('<b>Sources:</b> shared/vector_store.py; modules/tutor/retriever.py; orchestrator.py; knowledge.py; teaching.py; pipeline.py.', 'SmallA')

page('Equity research: evidence to report', '09 | The deepest domain pipeline')
table(['Stage','Implementation behavior'],[
 ['Resolve','Map a company name / ticker to a target and identify the report type or entity.'],
 ['Gather','Fetch statement tables, company and price data, headlines and available supporting information. Normalize units, periods and source differences.'],
 ['Analyze','Compute statement trends, financial ratios, cash-flow measures, fundamental signals and investor-style lenses using code.'],
 ['Value','Run a company-appropriate valuation: DCF for suitable companies; bank-specific dividend / book-value approaches; peer and other cross-checks.'],
 ['Record provenance','A ledger distinguishes actuals, calculations, estimates, assumptions, source text and AI interpretation.'],
 ['Audit numbers','Check evidence and consistency; valuation can be withheld when the audit finds blocking issues.'],
 ['Narrate and debate','LLM agents write evidence-linked narrative and bull / bear / judge views; the implementation can run narrative tasks concurrently.'],
 ['Audit narrative','Detect unsupported numeric claims and record verification findings. Missing source coverage stays visible.'],
 ['Build and save','Create structured report data, summary and versioned owner-scoped saved reports; export through report renderers.']
], [103,388])
h('The valuation explanation to practise')
p('A DCF forecasts free cash flow, discounts it and bridges enterprise value to equity value per share. WACC, terminal growth and other configured inputs are assumptions, not facts discovered by the LLM. Sensitivity tables and bull/base/bear cases expose how assumptions change the answer. A bank needs a different model because debt and capital have a different economic role.')
h('Important limits')
p('A provenance ledger improves auditability; it cannot make an upstream statement correct. FinBERT sentiment is an optional local component. Evidence gaps, stale sources, currency mismatches or absent data must remain explicit. Persisting a report may fail separately from computing it; the code can still return an unsaved report.')
p('<b>Sources:</b> modules/equity_research/intelligence/{pipeline,data,facts,analysis,valuation,audit,report}.py.', 'SmallA')

page('Markets, news and forecast validation', '10 | External and historical data')
h('Market and news ingestion')
p('Market analysis gathers real instrument / index context and uses it to ground the explanation. The repository integrates yfinance, screener.in for company statements, mfapi.in and AMFI for mutual-fund data, and RSS feeds for news. Provider coverage varies by workflow. Quote timestamps and market closures matter: "live" does not guarantee exchange-grade real-time data.')
p('News is fetched, merged, deduplicated and ranked. Relevant headlines can be added to time-sensitive answers. Caching reduces repeated provider calls, but it creates a freshness tradeoff and must not hide a provider outage or stale snapshot.')
h('Forecast-validation data flow')
bullet('Retrieve and quality-check historical bars; record gaps, duplicate observations, outliers and corporate-action concerns; cache histories as Parquet where applicable.')
bullet('Construct historical features and forward log-return targets for configured horizons: 1, 5, 21, 63 and 126 bars.')
bullet('Run walk-forward evaluation with purging / embargo controls. Fit imputation, scaling and model selection only on allowed training observations.')
bullet('Compare candidates with baselines, select through validation and require confirmation on an untouched test segment. Permit "no_model_beats_baseline" and "insufficient_evidence" outcomes.')
bullet('Persist run metadata, progress and results. A FIFO worker dispatches jobs to spawned child processes so timeouts can terminate expensive work.')
h('Do not confuse two meanings of forecast')
p('<b>Valuation scenarios</b> project operating assumptions into cash flows and fair value. <b>Statistical return forecasts</b> evaluate historical predictability against baselines. A plausible cash-flow story does not prove that the share price is predictable.')
h('Availability constraint')
p('Automatic forecast and scenario jobs are skipped in account mode by the research pipeline, and integrations with unsafe shared global state are restricted. Do not present all optional compute features as universally enabled for signed-in users.')
p('<b>Sources:</b> shared/news.py; modules/market/; modules/equity_research/forecast/{data,features,backtest,selection,models,jobs,contracts}.py; scenario_backtest/.', 'SmallA')

page('Storage, identity and reliability', '11 | State and trust boundaries')
table(['State','Where / representation','Why it exists'],[
 ['Financial profile and transactions','SQLite via SQLAlchemy; profile facts and source metadata','Reuse known facts and support user edits'],
 ['Conversation history and requests','Durable owner/session records plus a compatibility cache','Restart recovery, context and successful-request replay'],
 ['Learning progress','SQLite mastery and interaction-history JSON','Personalized teaching across turns'],
 ['Research reports','Versioned owner-scoped structured report JSON','Reopen, compare versions and export'],
 ['Statement previews','SQLite rows, expiry and import results','Durable preview and atomic idempotent import'],
 ['Semantic knowledge','FAISS files and metadata JSON','Concept retrieval'],
 ['ML / historical artifacts','Local model checkpoints, datasets and Parquet caches','Inference and reproducible validation']
], [119,205,167])
h('Authentication versus identity')
p('Private mode uses a browser/device owner id for local workflows; that id is not proof of a logged-in account. Account mode adds cookie-based authentication, password hashing and optional configured Google sign-in. The backend binds requests to the authenticated owner and checks ownership rather than trusting an arbitrary browser-supplied identifier.')
h('Concurrency and failure handling')
p('In-process session locks serialize conversation work for a session. The database supports durable records. Statement imports also acquire a database writer transaction before deduplication. These protections have different scopes: an in-memory lock alone does not coordinate multiple backend processes.')
p('The LLM client supports Groq with Gemini fallback. QA handling turns provider errors into controlled degraded responses. A number-matching guard can remove unsupported figures on supported evidence routes; finance engine output may be tagged rather than rewritten. Source interpretation, nonnumeric claims and all subtle contradictions remain outside any simple numeric check.')
p('<b>Sources:</b> api/auth.py; shared/user_store.py; shared/conversation_memory.py; shared/statement_store.py; core/session.py; modules/qa/trust.py.', 'SmallA')

page('Voice, avatars and latency', '12 | Presentation over the same answer')
h('Common flow')
p('Speech recognition or a text message produces a query. The shared QA pipeline produces a written answer. Presentation code can create a shorter spoken version, synthesize audio and send it to a browser or an avatar integration. Mode and channel affect presentation; they should preserve the underlying answer and owner scope.')
table(['Path','How to explain it'],[
 ['Text / conversational UI','Written answer; audio presentation can be prepared separately.'],
 ['Live Avatar','Browser recognition, shared answer pipeline, spoken text and local Piper speech; browser face or 3D presentation.'],
 ['Local avatar engine','Optional engine service with chunking, audio/video framing, motion and supported rendering backends.'],
 ['LiveTalking','Optional separate lip-sync service and WebRTC presentation path.'],
 ['Tavus','Optional hosted conversational-video integration; availability depends on configuration and account-mode restrictions.']
], [130,361])
h('A useful latency decomposition')
p('End-to-end latency = recognition / input time + queue and warm-up time + domain data fetch + computation + LLM narration + speech synthesis + transport and browser buffering. Measure time to useful text, first audible word and sustained playback separately.')
h('Measured evidence and its limits')
p('docs/MEASUREMENTS.md records partial measurements from 22 October 2026. Its browser avatar comparison uses a mocked chat reply and cached spoken text; it is not a complete chat-to-speech benchmark. It records GPU contention when both avatar services speak together, and some end-to-end measurements were still pending. Cite its setup and limitations if discussing those results.')
h('Failure and interruption')
p('Optional rendering services can become unavailable while chat remains usable. Interrupting server generation does not automatically remove audio already buffered in a WebRTC client. Correct barge-in needs both cancellation upstream and management of client playback / queued media.')
p('<b>Sources:</b> api/routes/live.py; modules/qa/present.py; ai/llm/spoken.py; ai/speech/live_tts.py; avatar_engine/; livetalking_adapter/; docs/MEASUREMENTS.md.', 'SmallA')

page('Validation and a future scaling design', '13 | Be precise about what is proven')
h('What the repository tests')
table(['Area','Examples present in tests/'],[
 ['Shared answering','Unified pipeline, grounding, routing, intent, dialogue and adversarial behavior'],
 ['Persistence and identity','Accounts, conversation memory, owner isolation, durable statement imports and audio persistence'],
 ['Finance and tutoring','Financial tools, model wrappers, transaction/profile flows, retrieval, quizzes and mastery'],
 ['Research and forecasts','Ratios, valuation, audit agents, report exports, historical backtests and leakage checks'],
 ['Resource / media handling','Upload limits, compressed archives, avatar framing, replicas and stream behavior']
], [123,368])
p('<b>Verification for this guide:</b> source inspection and PDF generation/structure checks only. No new test pass count, production load result or model performance score is claimed.')
h('What to measure before making performance claims')
bullet('Routing accuracy on independently labeled finance, tutor, market, equity and general questions.')
bullet('Model performance on held-out users or chronological future data, with baseline comparison and confidence intervals.')
bullet('Provider failure rate, cache age, p50/p95 request latency, active sessions, memory use and GPU contention.')
bullet('Grounding precision/recall, unsupported claims that slip through, and owner-isolation behavior across channels.')
h('Proposed production evolution: not implemented architecture')
p('Keep the API stateless by moving process-local coordination and shared session state to suitable shared infrastructure. Move long-running forecasts and GPU rendering behind explicit worker queues with cancellation and resource limits. Use a shared transactional database and object storage for durable artifacts, version schemas and model files, and add provider health/freshness metrics.')
p('Introduce distributed coordination only where measured concurrency requires it. Do not add Kafka, Spark, Airflow or a microservice fleet simply to make the diagram larger: the present system is an application pipeline with local jobs and provider fetching, not a distributed lakehouse or streaming ETL platform.')

page('Interview questions and short answers', '14 | Practise aloud')
questions = [
 ('Why not send every question directly to an LLM?', 'Profiles, calculations and valuations need structured inputs, reproducible arithmetic and persistent state. Domain tools compute results; the model helps explain them.'),
 ('Is ARIA a RAG application?', 'The tutor retrieves semantically matched concepts with Sentence-BERT and FAISS. Other modules mainly use structured data and deterministic tools. The whole system is broader than one document-RAG pipeline.'),
 ('Why XGBoost and LSTM?', 'XGBoost fits tabular risk features; the spend LSTM models temporal category patterns. That rationale still needs baseline evaluation: a complex model must demonstrate a useful improvement.'),
 ('What happens if a model or provider is missing?', 'Behavior is route-specific: the tutor can use a conversational fallback, optional sentiment can be absent, and provider/LLM failures are surfaced through warnings or controlled degraded answers. Not every failure has an equivalent-quality fallback.'),
 ('How do you prevent hallucinations?', 'Use fetched structured evidence, code-based calculations, provenance labels, audits and route-specific numeric checks. These reduce unsupported claims; they do not prove every sentence true.'),
 ('How do retries avoid duplicate data?', 'Completed chat requests can replay by request_id. Statement imports separately use persisted previews, deduplication, writer serialization and an atomic import receipt.'),
 ('How do you avoid time-series leakage?', 'Separate past training observations from future evaluation, purge overlapping targets, use an embargo and fit preprocessing inside each training split. Select using validation and confirm on untouched test data.'),
 ('What is the biggest limitation?', 'Synthetic finance/training data and external-source quality limit real-world claims. Optional integrations and process-local state also constrain deployment scale.'),
 ('How would you scale it?', 'First measure the bottleneck. Isolate heavy jobs, externalize shared state and coordination, strengthen database/artifact operations, and add observability before splitting services.'),
 ('What did you personally build?', 'Name the exact modules you owned, trace one input to output, explain a difficult bug or tradeoff, and report only results you actually measured.')
]
for q,a in questions:
    p('<b>'+q+'</b><br/>'+a)
p('<b>Final rehearsal:</b> Draw the UI -> API -> QA pipeline -> four modules -> storage/providers diagram. Trace one uploaded statement and one research request. Then explain synthetic-data limits and one production improvement in your own words.')

page('Code map and revision checklist', '15 | Find the implementation quickly')
table(['Responsibility','Files to open'],[
 ['Application / identity','api/main.py; api/auth.py; api/resource_limits.py; web/src/'],
 ['Unified question contract','modules/qa/models.py; pipeline.py; focus.py; trust.py; present.py'],
 ['Routing / durable turns','core/router.py; core/orchestrator.py; core/session.py; shared/conversation_memory.py'],
 ['Profile / import storage','shared/user_store.py; shared/statement_store.py; modules/finance/statement_import.py'],
 ['Finance behavior','modules/finance/pipeline.py; personal.py; engine.py; orchestrator.py; features.py'],
 ['Finance ML / optimization','modules/finance/risk_model.py; forecast_model.py; anomaly.py; budget_optimize.py; train/'],
 ['Tutor / semantic index','modules/tutor/orchestrator.py; retriever.py; knowledge.py; teaching.py; shared/vector_store.py'],
 ['Market / news ingestion','modules/market/; shared/news.py; shared/company_resolver.py'],
 ['Research / provenance','modules/equity_research/intelligence/{pipeline,data,facts,analysis,valuation,audit,report}.py'],
 ['Historical validation','modules/equity_research/forecast/; modules/equity_research/scenario_backtest/'],
 ['LLM / voice / avatars','ai/llm/groq_client.py; ai/llm/spoken.py; ai/speech/; avatar_engine/; livetalking_adapter/'],
 ['Architecture / evidence','README.md; docs/QA_PIPELINE.md; docs/MEASUREMENTS.md; tests/']
], [132,359])
h('Before joining the interview')
bullet('Be able to give the 90-second explanation without reading.')
bullet('Know which features are deterministic, learned, retrieved or generated.')
bullet('Have one real example of parsing, deduplication, retry handling or grounding ready.')
bullet('State whether a number is measured, configured, calculated or assumed.')
bullet('Describe your own contribution and one limitation candidly.')
p('This document is an interview study guide based on local source inspection on 24 October 2026. Historical documentation and comments can lag implementation. Sources above are repository references rather than claims of live-provider availability.', 'SmallA')

def footer(canvas, doc):
    canvas.saveState()
    w,h=A4
    canvas.setStrokeColor(colors.HexColor('#d1dce5')); canvas.line(52,40,w-52,40)
    canvas.setFont('Helvetica',8); canvas.setFillColor(BLUE)
    canvas.drawString(52,27,'ARIA | Interview architecture & data pipeline | 24 Oct 2026')
    canvas.drawRightString(w-52,27,str(doc.page))
    canvas.restoreState()

doc=SimpleDocTemplate(str(OUT),pagesize=A4,rightMargin=52,leftMargin=52,topMargin=43,bottomMargin=54,
    title='ARIA - Interview Data Pipeline and Project Architecture',author='ARIA Project',
    subject='Source-reviewed architecture, ingestion, ML, retrieval, research and interview preparation')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
(ROOT/'reports'/'ARIA_Interview_Guide_Content.txt').write_text('\n\n'.join(source_text),encoding='utf-8')
print(OUT)
