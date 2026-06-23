# Stock Analyst AI — Agentic Development Prompts
## Phase 3: Quality & UX | Phase 4: Production Hardening | Test Suites

---

## PROMPT 3.1 — Evaluation Framework & Hallucination Detection

```
You are implementing the quality evaluation framework for the Stock Analyst AI platform.
All 7 agents and the Citation Enforcer are complete and working.
Working directory: eval/ and packages/agents/shared/

CONTEXT:
Before the system goes to real analysts, we need an automated evaluation suite that runs
each agent against known-good test cases and measures citation coverage, hallucination rate,
format compliance, and latency. This is also the CI gate for Phase 3.

TASK 1 — Create eval/datasets/lynch_pitch_eval.json:
Manually-curated golden evaluation dataset for the Lynch Pitch Agent.
Create 5 test cases — use AAPL as the test company with a realistic synthetic 10-K summary:

{
  "agent": "lynch_pitch",
  "version": "1.0",
  "test_cases": [
    {
      "test_id": "LP-001",
      "name": "AAPL standard pitch with full filings",
      "coverage_id": "AAPL_EVAL_2023",
      "documents": ["aapl_10k_2021.pdf", "aapl_10k_2022.pdf", "aapl_10k_2023.pdf"],
      "must_answer_questions": [1, 2, 3, 4, 5, 6, 7, 8],
      "must_not_contain": [
        "will grow", "analysts predict", "expected to increase", 
        "exciting opportunity", "compelling valuation", "robust growth"
      ],
      "required_citation_format": "\\[[^\\]]+,\\s*[^\\]]+\\]:\\s*\"[^\"]+\"",
      "min_citation_coverage": 0.95,
      "max_word_count": 900,
      "required_company_type_mention": ["slow grower", "stalwart", "fast grower", "cyclical", "turnaround", "asset play"],
      "must_cite_sections": ["Business", "Risk Factors", "Financial Statements"]
    },
    {
      "test_id": "LP-002",
      "name": "Company with only 1 year of filings",
      "coverage_id": "NEWCO_EVAL_2023",
      "documents": ["newco_10k_2023.pdf"],
      "must_answer_questions": [1, 2, 3, 4, 5, 6, 7, 8],
      "must_contain_not_found": ["Q4", "Q7"],
      "min_citation_coverage": 0.80,
      "max_word_count": 900
    },
    {
      "test_id": "LP-003",
      "name": "Pre-revenue company",
      "notes": "Company has no revenue yet — Q3 answer must state Not Found for margins",
      "coverage_id": "STARTUP_EVAL_2023",
      "documents": ["startup_s1.pdf"],
      "must_answer_questions": [1, 2, 3, 4, 5, 6, 7, 8],
      "q3_must_contain_not_found": true,
      "min_citation_coverage": 0.85
    },
    {
      "test_id": "LP-004",
      "name": "Hallucination resistance — agent must not invent metrics",
      "coverage_id": "SPARSE_EVAL_2023",
      "documents": ["sparse_10k_no_margins.pdf"],
      "must_not_state_gross_margin": true,
      "min_citation_coverage": 0.95
    },
    {
      "test_id": "LP-005",
      "name": "Citation format compliance",
      "coverage_id": "AAPL_EVAL_2023",
      "documents": ["aapl_10k_2023.pdf"],
      "all_citations_must_match_regex": "\\[[^\\]]+,\\s*[^\\]]+\\]:\\s*\"[^\"]{10,}\"",
      "min_citation_coverage": 0.95
    }
  ]
}

Create similar eval files for: munger_invert (5 cases), earnings_monitor (5 cases), industry_analyst (3 cases), kpi_tracker (3 cases).

TASK 2 — Create eval/runners/run_eval.py:
Command-line evaluation runner:

python eval/runners/run_eval.py --agent lynch_pitch --env dev [--output-html eval/reports/]

class EvalRunner:
    def __init__(self, agent_name: str, env: str):
        self.agent_name = agent_name
        self.dataset = self._load_dataset(f"eval/datasets/{agent_name}_eval.json")
        
    async def run_all(self) -> EvalReport:
        results = []
        for case in self.dataset["test_cases"]:
            result = await self.run_case(case)
            results.append(result)
        return EvalReport(agent=self.agent_name, results=results)
    
    async def run_case(self, case: dict) -> CaseResult:
        start = time.monotonic()
        # 1. Set up test coverage with test documents (use real indexed documents from eval fixtures)
        # 2. Run the agent via the API: POST /coverages/{eval_coverage_id}/tasks/{agent_task}
        # 3. Poll task status until complete
        # 4. Retrieve the output from research_outputs
        # 5. Evaluate output against all checks in the test case
        latency_ms = int((time.monotonic() - start) * 1000)
        
        checks = self._run_checks(case, output_content)
        return CaseResult(
            test_id=case["test_id"],
            name=case["name"],
            passed=all(c.passed for c in checks),
            checks=checks,
            citation_coverage_pct=actual_coverage,
            latency_ms=latency_ms,
            llm_used=output.llm_used,
            tokens_used=output.tokens_used,
        )
    
    def _run_checks(self, case: dict, content: str) -> list[CheckResult]:
        checks = []
        
        # Check: all required questions answered (## Q{n}: header present)
        for q_num in case.get("must_answer_questions", []):
            pattern = rf"###\s*Q{q_num}:"
            checks.append(CheckResult(
                name=f"Q{q_num}_answered",
                passed=bool(re.search(pattern, content, re.IGNORECASE)),
                detail=f"Question {q_num} header {'found' if ... else 'MISSING'}"
            ))
        
        # Check: forbidden phrases not present
        for phrase in case.get("must_not_contain", []):
            checks.append(CheckResult(
                name=f"no_{phrase.replace(' ', '_')}",
                passed=phrase.lower() not in content.lower(),
                detail=f"Forbidden phrase '{phrase}' {'not found (good)' if ... else 'FOUND (bad)'}"
            ))
        
        # Check: citation coverage meets minimum
        actual_cov = self._compute_citation_coverage(content)
        min_cov = case.get("min_citation_coverage", 0.95)
        checks.append(CheckResult(
            name="citation_coverage",
            passed=actual_cov >= min_cov,
            detail=f"Citation coverage: {actual_cov:.1%} (need ≥{min_cov:.0%})"
        ))
        
        # Check: word count
        if "max_word_count" in case:
            wc = len(content.split())
            checks.append(CheckResult(
                name="word_count",
                passed=wc <= case["max_word_count"],
                detail=f"Word count: {wc} (max {case['max_word_count']})"
            ))
        
        # Check: citation format regex
        if "all_citations_must_match_regex" in case:
            # Find all citation-like patterns and verify they match the strict regex
            ...
        
        return checks
    
    def generate_html_report(self, report: EvalReport, output_path: str) -> None:
        # Generate HTML report using Jinja2 template
        # Show: pass/fail per test case, pass/fail per check, aggregate metrics
        # Color coding: green=pass, red=fail, yellow=warning
        # Include: citation_coverage histogram, latency distribution, token usage

@dataclass
class EvalReport:
    agent: str
    results: list[CaseResult]
    
    @property
    def pass_rate(self) -> float:
        return sum(1 for r in self.results if r.passed) / len(self.results)
    
    @property
    def avg_citation_coverage(self) -> float:
        return sum(r.citation_coverage_pct for r in self.results) / len(self.results)
    
    @property
    def avg_latency_ms(self) -> float:
        return sum(r.latency_ms for r in self.results) / len(self.results)
    
    @property
    def hallucination_rate(self) -> float:
        # Computed from Citation Enforcer check results in each CaseResult
        ...

TASK 3 — Enhance Citation Enforcer with semantic hallucination detection:
In packages/agents/shared/citation_enforcer.py, enhance _check_quotes_exist_in_rag:

Current: BM25 exact-match search for quote
Enhancement: if BM25 returns no results, try embedding similarity as fallback:
  - Embed the quote text
  - Dense search with very high similarity threshold (>0.92)
  - If dense also returns nothing: confirmed hallucination
  - If dense finds it but BM25 didn't: "paraphrase detected" (log as WARNING not FAIL,
    because the agent may have slightly rephrased a real quote — flag for human review)

Add to ValidationResult:
  paraphrase_warnings: list[str]  # quotes found by dense but not BM25 (possible paraphrase)

Log all confirmed hallucinations and paraphrase warnings to agent_audit_log with action="hallucination_detected" or "paraphrase_warning".

TASK 4 — Add CI gate for evaluation:
In .gitea/workflows/ci.yml, add job eval-gate (runs on merge to main only):
  - Setup test fixtures (pre-indexed eval coverages)
  - Run eval runner for each agent
  - Fail CI if any agent's pass_rate < 1.0 (all eval cases must pass)
  - Fail CI if avg_citation_coverage < 0.95
  - Fail CI if hallucination_rate > 0.005 (0.5%)
  - Output HTML report as CI artifact

CONSTRAINTS:
- Eval fixtures (pre-indexed test coverages) must be reproducible: store the fixture documents in eval/fixtures/ and always re-index them before the eval run (delete and re-ingest to avoid state contamination)
- The HTML report must be self-contained (inline CSS) — no external CDN dependencies
- Paraphrase warnings must NOT cause citation validation to fail — they are informational flags
- The eval runner must run all cases sequentially, not in parallel, to avoid Celery worker contention

ACCEPTANCE CRITERIA:
1. python eval/runners/run_eval.py --agent lynch_pitch runs all 5 cases
2. HTML report generated at eval/reports/lynch_pitch_{timestamp}.html
3. Hallucination detection flags a known bad output (quote changed by 2 words) as paraphrase_warning
4. Hallucination detection flags a completely invented quote as confirmed hallucination
5. CI eval-gate job passes on the main branch
```

---

## PROMPT 3.2 — WebSocket Streaming & Research Output UI

```
You are implementing real-time streaming and the research output UI for the Stock Analyst AI platform.
All agents are working. The evaluation framework passes. LangSmith tracing is configured.
Working directory: apps/api/ and apps/web/

CONTEXT:
Analysts need to see agent outputs stream in real-time — watching the bull case write itself
paragraph by paragraph is a much better experience than staring at a spinner for 90 seconds.
The streaming architecture: LangGraph callbacks → Redis pub/sub → WebSocket → browser.

TASK 1 — Implement Redis pub/sub streaming in apps/api/services/streaming.py:

class StreamingService:
    def __init__(self, redis_url: str):
        import redis.asyncio as aioredis
        self.redis = aioredis.from_url(redis_url)
    
    async def publish_event(self, task_id: str, event: dict) -> None:
        # Serialize event to JSON and publish to Redis channel "task:{task_id}"
        channel = f"task:{task_id}"
        await self.redis.publish(channel, json.dumps(event))
    
    async def subscribe_events(self, task_id: str):
        # Async generator yielding events from Redis pub/sub
        # Yields until receiving a "complete" or "error" event type, then stops
        channel = f"task:{task_id}"
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    event = json.loads(message["data"])
                    yield event
                    if event.get("type") in ("complete", "error"):
                        break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

Event types and payloads:
{"type": "progress", "step": "retrieving_citations", "pct": 30, "detail": "Searching 6 topics..."}
{"type": "chunk", "content": "...", "citations": [...]}  # streaming text as LLM generates
{"type": "citation_found", "doc": "AAPL 10-K 2023", "section": "Business", "quote": "..."}
{"type": "enforcer_running", "attempt": 1}
{"type": "enforcer_result", "approved": true, "citation_coverage_pct": 0.97}
{"type": "complete", "output_id": "...", "citation_coverage_pct": 0.97, "llm_used": "claude-opus-4-8"}
{"type": "error", "code": "CITATION_ENFORCER_FAIL", "retry_count": 2, "detail": "..."}
{"type": "partial", "output_id": "...", "citation_coverage_pct": 0.82, "reason": "Max retries exceeded"}

TASK 2 — Add LangGraph callbacks that emit streaming events:
In packages/agents/shared/base_agent.py, add a streaming callback handler:

from langchain.callbacks.base import AsyncCallbackHandler

class AgentStreamingCallback(AsyncCallbackHandler):
    def __init__(self, task_id: str, streaming_service: StreamingService):
        self.task_id = task_id
        self.streaming_svc = streaming_service
        self.buffer = ""
        
    async def on_llm_new_token(self, token: str, **kwargs) -> None:
        self.buffer += token
        # Emit chunk every ~100 chars to avoid flooding
        if len(self.buffer) >= 100:
            await self.streaming_svc.publish_event(self.task_id, {
                "type": "chunk",
                "content": self.buffer,
                "citations": self._extract_citations(self.buffer)
            })
            self.buffer = ""
    
    async def on_llm_end(self, response, **kwargs) -> None:
        if self.buffer:
            await self.streaming_svc.publish_event(self.task_id, {
                "type": "chunk", "content": self.buffer, "citations": []
            })
            self.buffer = ""
    
    def _extract_citations(self, text: str) -> list[dict]:
        # Extract any complete citations from the buffered text
        from packages.agents.shared.citation_enforcer import CITATION_PATTERN
        return [{"doc": d, "section": s, "quote": q} 
                for d, s, q in CITATION_PATTERN.findall(text)]

Update BaseAgent._call_llm to pass the streaming callback when streaming=True:
  - Add streaming=True to LiteLLM call
  - Pass AgentStreamingCallback as a callback handler

TASK 3 — Implement WebSocket endpoint in apps/api/routers/tasks.py:

from fastapi import WebSocket, WebSocketDisconnect

@router.websocket("/ws/tasks/{task_id}")
async def task_websocket(websocket: WebSocket, task_id: str,
                          current_user: CurrentUser = Depends(get_current_user_ws)):
    # Note: WebSocket auth requires extracting token from query param (not header)
    # URL: /ws/tasks/{task_id}?token={jwt}
    await websocket.accept()
    streaming_svc = StreamingService(settings.REDIS_URL)
    
    try:
        # Check if task is already complete (user reconnected after brief disconnect)
        task = await get_task_by_id(task_id, current_user.tenant_id, db)
        if task.status == "completed":
            # Send the final state immediately
            await websocket.send_json({"type": "already_complete", "output_id": task.result.get("output_id")})
            await websocket.close()
            return
        
        # Subscribe and forward events
        async for event in streaming_svc.subscribe_events(task_id):
            await websocket.send_json(event)
            if event.get("type") in ("complete", "error", "partial"):
                break
                
    except WebSocketDisconnect:
        pass  # Client disconnected — no cleanup needed

def get_current_user_ws(token: str = Query(...)) -> CurrentUser:
    # Same JWT validation as HTTP auth, but token comes from query param
    # Raises HTTPException → becomes WebSocket close with code 1008

TASK 4 — Build Research Output pages in Next.js:

apps/web/app/(protected)/coverages/[id]/research/bull-case/page.tsx:
Client component with streaming:

const BullCasePage = ({ params }: { params: { id: string } }) => {
  const [streamedContent, setStreamedContent] = useState("")
  const [citations, setCitations] = useState([])
  const [status, setStatus] = useState("idle") // idle | loading | streaming | complete | error | partial
  const [citationCoverage, setCitationCoverage] = useState<number | null>(null)
  
  const runLynchPitch = async () => {
    setStatus("loading")
    // POST to /orchestrate with "run bull case"
    const { task_id } = await api.post(`/coverages/${params.id}/tasks/lynch-pitch`, {})
    
    setStatus("streaming")
    // Open WebSocket
    const ws = new WebSocket(`${wsBase}/ws/tasks/${task_id}?token=${session.accessToken}`)
    
    ws.onmessage = (e) => {
      const event = JSON.parse(e.data)
      switch(event.type) {
        case "chunk":
          setStreamedContent(prev => prev + event.content)
          setCitations(prev => [...prev, ...event.citations])
          break
        case "enforcer_running":
          // Show enforcer status indicator
          break
        case "complete":
          setStatus("complete")
          setCitationCoverage(event.citation_coverage_pct)
          ws.close()
          break
        case "partial":
          setStatus("partial")
          ws.close()
          break
        case "error":
          setStatus("error")
          ws.close()
          break
      }
    }
  }
  
  return (
    <div>
      {status === "idle" && <Button onClick={runLynchPitch}>Generate Bull Case</Button>}
      {status === "loading" && <LoadingSpinner text="Preparing analysis..." />}
      {(status === "streaming" || status === "complete") && (
        <ResearchOutput content={streamedContent} citations={citations} />
      )}
      {status === "partial" && (
        <PartialWarningBanner reason="Citation validation partially passed. Manual review recommended." />
      )}
      {status === "complete" && (
        <CitationCoverageBadge pct={citationCoverage} />
      )}
    </div>
  )
}

TASK 5 — Create shared ResearchOutput renderer component:
apps/web/components/research/research-output.tsx:
- Renders markdown content with custom citation rendering
- Custom markdown renderer: detect [Doc, Section]: "quote" patterns → render as citation superscripts
- Citation superscripts are clickable → open CitationModal
- CitationModal: shows full document name, section, exact quote, and a "View in Document" link
  (links to a pre-signed MinIO URL for the original PDF, opened in new tab)
- Support for streaming: content prop updates as new chunks arrive → appends smoothly
- "PARTIAL" banner: orange banner at top if enforcer_status="partial"
- Citation coverage badge: bottom-right corner showing percentage

apps/web/components/research/citation-tooltip.tsx:
- Wraps inline citation text in a shadcn Tooltip
- Tooltip content: document name + section + "Open document" button
- The button calls GET /coverages/{id}/documents/{doc_id}/presigned-url → opens in new tab

TASK 6 — Add side-by-side Bull/Bear view:
apps/web/app/(protected)/coverages/[id]/research/page.tsx:
- Desktop: two-column grid showing bull case left, bear case right
- Mobile: tabs switching between bull and bear
- Each panel: full ResearchOutput renderer with its own streaming state
- "Run Both" button: triggers Lynch Pitch and Munger Invert simultaneously (two parallel WebSocket connections)
- Shows completion status per panel independently

CONSTRAINTS:
- WebSocket auth MUST validate the JWT token from query param — reject connection if invalid
- Streaming chunks must not break mid-citation — buffer until a complete citation is detected before emitting citation_found event
- The ResearchOutput component must handle content prop being updated by appending (not replacing) — use useRef to track the last rendered position
- On WebSocket reconnect (browser tab becomes active after being hidden), check task status first

ACCEPTANCE CRITERIA:
1. POST /tasks/lynch-pitch → WebSocket receives streaming chunks as LLM generates text
2. Citation events appear in WebSocket stream as each citation is found
3. Complete event arrives with citation_coverage_pct when enforcer approves
4. Bull case page renders streaming content in real-time with citation superscripts
5. Clicking a citation superscript opens the CitationModal with correct document info
6. "PARTIAL" banner appears when enforcer_status="partial"
7. Side-by-side view shows both bull and bear cases simultaneously on desktop
```

---

## PROMPT 3.3 — PDF Export, Analyst Notes & Earnings Calendar

```
You are implementing the export, notes, and automation features for the Stock Analyst AI platform.
WebSocket streaming and all research output pages are complete.
Working directory: apps/api/ and apps/web/

TASK 1 — Implement PDF report generation at apps/api/services/report_generator.py:

Use WeasyPrint to generate PDFs from HTML:

class ReportGenerator:
    def generate_coverage_report(self, coverage_id: str, tenant_id: str,
                                  include_sections: list[str] | None = None) -> bytes:
        # Fetch all approved research_outputs for this coverage from DB
        # Build HTML structure:
        # - Cover page: company name, ticker, exchange, generated date
        # - Table of contents
        # - Industry Primer section (if approved)
        # - Bull Case section (Lynch Pitch, if approved)
        # - Bear Case section (Munger Invert, if approved)
        # - Latest Quarterly Update section (if approved)
        # - KPI Time-Series section: tables of key metrics
        # - Citations section: numbered footnotes linking back to body text
        #
        # Convert inline [Doc, Section]: "quote" citations to footnote numbers:
        #   In body: replace with ¹, ², etc.
        #   At end: full citation list with numbers
        #
        # Use WeasyPrint: from weasyprint import HTML; pdf_bytes = HTML(string=html).write_pdf()
        # Return raw PDF bytes

    def _build_html(self, coverage: dict, outputs: list[dict], kpis: list[dict]) -> str:
        # Use Jinja2 template at apps/api/templates/report.html
        # Template uses CSS for print layout: @page { size: A4; margin: 2cm; }
        # Font: embed a professional serif (e.g., Georgia) as base64 for portability

Add API endpoint in apps/api/routers/outputs.py:
GET /api/v1/coverages/{id}/report.pdf:
  Auth: viewer minimum (all roles can download)
  Query params: sections (comma-separated, optional, default all)
  Returns: Response with content-type: application/pdf, content-disposition: attachment
  If no approved outputs: 404 with message "No approved research outputs found"

Add download button to coverage layout: apps/web/app/(protected)/coverages/[id]/layout.tsx
  "Download Report" button → calls GET /report.pdf → triggers browser download
  Show spinner while generating (typically 3-5 seconds)

TASK 2 — Create Analyst Notes editor component:
apps/web/components/notes/analyst-notes-editor.tsx:

Uses Tiptap with a custom citation extension:

const CitationExtension = Extension.create({
  name: 'citation',
  addCommands() {
    return {
      insertCitation: (citation: CitationData) => ({ commands }) => {
        return commands.insertContent(
          `[${citation.doc}, ${citation.section}]: "${citation.quote}"`
        )
      }
    }
  },
  addKeyboardShortcuts() {
    return {
      '@': () => {
        // Trigger citation search popup
        this.editor.emit('openCitationSearch')
        return true
      }
    }
  }
})

Component features:
- When user types @: open a citation search dialog
  - Input field: search query
  - Results: call GET /coverages/{id}/search?q={query} → returns top 5 RAG results
  - Select a result → insert as formatted citation in the editor
- Toolbar: Bold, Italic, H2, H3, Bullet list, Numbered list, Insert Citation (@)
- Auto-save: debounced 2s, POST /coverages/{id}/notes with content
- Notes are stored in a new table: coverage_notes (coverage_id, tenant_id, content, updated_at)
- Export notes: included in PDF report as "Analyst Notes" section at the end

Create the coverage_notes table migration:
  coverage_notes: id UUID, coverage_id FK, tenant_id FK, content TEXT, updated_at DATETIME
  Add to Alembic migration and RLS policy.

Add API endpoint: POST/GET /api/v1/coverages/{id}/notes

TASK 3 — Implement Earnings Calendar & Auto-Trigger:
File: apps/api/tasks/scheduler.py

EARNINGS_MONITOR_SCHEDULE = "0 6 * * *"  # 6am daily

@celery_app.task
def check_for_new_filings():
    # Called by Celery Beat every day at 6am
    # For each coverage with status="active":
    #   1. Check SEC EDGAR for new filings since last_updated
    #   2. If new 10-Q or 10-K found:
    #      a. Auto-ingest the new filing (call ingest_document_task)
    #      b. After ingestion completes: dispatch EarningsMonitorAgent task
    #      c. Send notification to all analyst/senior_analyst users in this tenant
    # Use asyncio.run() to call async SEC EDGAR connector from this sync Celery task
    
Configure Celery Beat in apps/api/celery_config.py:
from celery.schedules import crontab
beat_schedule = {
    "check-new-filings-daily": {
        "task": "apps.api.tasks.scheduler.check_for_new_filings",
        "schedule": crontab(hour=6, minute=0),
    }
}

TASK 4 — Implement notification system:
File: apps/api/services/notifications.py

class NotificationService:
    def __init__(self, redis_url: str, smtp_config: dict | None = None):
        self.redis = aioredis.from_url(redis_url)
        self.smtp = smtp_config
    
    async def notify_earnings_complete(self, coverage: dict, output: dict, 
                                        tenant_id: str, db) -> None:
        # Get all analyst + senior_analyst users for this tenant
        # Send in-app notification: publish to Redis channel "notifications:{tenant_id}"
        # Format: {"type": "earnings_complete", "ticker": "AAPL", "coverage_id": "...", 
        #          "output_id": "...", "timestamp": "..."}
        #
        # Optionally: send email if SMTP configured
        # Email body: "New quarterly analysis available for {company_name} ({ticker}).
        #   Log in to view the latest earnings comparison."
        
    async def get_unread_notifications(self, tenant_id: str, user_id: str) -> list[dict]:
        # Return unread notifications for this user from Redis sorted set
        # (Stored as: ZADD "user_notifications:{user_id}" timestamp notification_json)
        
    async def mark_read(self, user_id: str, notification_id: str) -> None:
        # Mark notification as read (update in Redis)

Add notification bell to Next.js sidebar:
- Shows unread count badge (red dot with number)
- On click: dropdown list of recent notifications
- Click notification → navigate to the relevant coverage/output
- Poll GET /notifications/unread every 30 seconds (or use Server-Sent Events)

TASK 5 — Add LLM Cost Dashboard:
API endpoint: GET /api/v1/admin/usage (admin only)
  - Queries agent_audit_log grouped by tenant_id, month, llm_used
  - Estimates cost: tokens_used * price_per_token (hardcode current model prices)
  - Returns: {"tenants": [{"tenant_id": "...", "monthly_costs": [{"month": "2025-01", "cost_usd": 12.50}]}]}

apps/web/app/(protected)/admin/usage/page.tsx (admin role only):
- Bar chart (Recharts): monthly cost per tenant
- Table: per-coverage breakdown for selected tenant
- Per-model breakdown: Claude vs GPT-4o vs Local
- Alert threshold input: admin sets max monthly spend per tenant (stored in tenants.settings JSONB)

CONSTRAINTS:
- WeasyPrint requires system-level font and library dependencies — document this in a Dockerfile.api
- The citation footnote conversion must handle nested citations correctly (citations within table cells)
- Celery Beat must be run as a SEPARATE container/process from the main worker — document this in docker-compose.yml
- Cost estimation: hard-code prices at implementation time; document that these need updating quarterly
  (Claude Opus 4.8: $15/1M input, $75/1M output; GPT-4o: $2.50/1M input, $10/1M output; Local: $0)

ACCEPTANCE CRITERIA:
1. GET /report.pdf returns a valid PDF with all approved sections
2. PDF contains footnote-style citations with numbers in body and full citations at end
3. Tiptap editor: type @ → citation search dialog opens → select result → citation inserted
4. Celery Beat: runs at 6am; if new AAPL 10-Q available, auto-ingests and triggers earnings monitor
5. Notification bell shows unread count; clicking a notification navigates to correct page
6. Admin usage page renders monthly cost bar chart grouped by tenant
```

---

## PROMPT 4.1 — k3s Cluster Setup & Helm Charts

```
You are implementing the production on-premise Kubernetes deployment for the Stock Analyst AI platform.
Phase 3 is complete. The system passes evaluation. Now deploying to k3s (lightweight Kubernetes).
Working directory: infra/

CONTEXT:
The production cluster has 4 nodes (Architecture §10.1):
- Control plane: 8 CPU / 32GB RAM (k3s server)
- App worker: 16 CPU / 64GB RAM (FastAPI, Next.js, Celery)
- ML/GPU worker: 16 CPU / 64GB RAM + GPU (Ollama, embedding model, reranker)
- Data node: 16 CPU / 128GB RAM / 10TB NVMe (PostgreSQL, Qdrant, MinIO, Redis)

TASK 1 — Create Kubernetes namespace manifests at infra/k8s/namespaces/:
Five namespace YAML files:
1. stock-analyst.yaml: namespace "stock-analyst" with label app=stock-analyst
2. stock-analyst-data.yaml: namespace "stock-analyst-data"
3. stock-analyst-ml.yaml: namespace "stock-analyst-ml"
4. stock-analyst-infra.yaml: namespace "stock-analyst-infra"
5. stock-analyst-obs.yaml: namespace "stock-analyst-obs"

Each namespace has ResourceQuota limiting total CPU and memory:
- stock-analyst: 32 CPU, 64Gi RAM
- stock-analyst-data: 32 CPU, 200Gi RAM
- stock-analyst-ml: 24 CPU, 80Gi RAM, 1 GPU
- stock-analyst-infra: 8 CPU, 32Gi RAM
- stock-analyst-obs: 8 CPU, 32Gi RAM

TASK 2 — Create Helm chart: infra/helm/stock-analyst-data/
Chart for all stateful data services. Directory structure:
  Chart.yaml (name: stock-analyst-data, version: 1.0.0)
  values.yaml (overridable defaults)
  templates/
    postgres/deployment.yaml, service.yaml, pvc.yaml, configmap.yaml
    qdrant/deployment.yaml, service.yaml, pvc.yaml
    minio/deployment.yaml, service.yaml, pvc.yaml
    redis/deployment.yaml, service.yaml, pvc.yaml

PostgreSQL template key specs:
- image: postgres:16
- PVC: 1Ti storage, storageClass: local-path, accessMode: ReadWriteOnce
- Node affinity: nodeSelectorTerms matching label role=data
- Resources: requests 4 CPU / 32Gi, limits 8 CPU / 64Gi
- Env vars: POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD from secretKeyRef (Vault-injected)
- Liveness probe: exec pg_isready -U postgres
- Init container: runs alembic upgrade head on first deployment
- PVC retention: persistentVolumeReclaimPolicy: Retain

Qdrant template key specs:
- image: qdrant/qdrant:latest
- PVC: 500Gi, storageClass: local-path, node affinity: role=data
- Resources: requests 4 CPU / 16Gi, limits 8 CPU / 32Gi
- Liveness: GET /healthz on port 6333
- Config: qdrant/config.yaml with production settings (grpc enabled, telemetry off)

MinIO template key specs:
- image: minio/minio:latest
- PVC: 10Ti (10TB), node affinity: role=data
- Command: server /data --console-address ":9001"
- Resources: requests 2 CPU / 8Gi, limits 4 CPU / 16Gi
- Liveness: exec mc ready local

Redis template key specs:
- image: redis:7-alpine
- PVC: 50Gi, node affinity: role=data
- Command: redis-server --appendonly yes --save 60 1
- Resources: requests 1 CPU / 4Gi, limits 2 CPU / 8Gi

TASK 3 — Create Helm chart: infra/helm/stock-analyst-app/
Chart for stateless application services:
  templates/
    api/deployment.yaml, service.yaml, hpa.yaml
    web/deployment.yaml, service.yaml
    celery-worker/deployment.yaml, hpa.yaml
    celery-beat/deployment.yaml  (single replica, no HPA)
    flower/deployment.yaml, service.yaml
    keycloak/deployment.yaml, service.yaml

FastAPI API Deployment:
- image: {{ .Values.registry }}/stock-analyst-api:{{ .Values.api.imageTag }}
- replicas: 3 (or HPA min: 2, max: 10, targetCPUUtilizationPercentage: 70)
- Node affinity: role=app
- Resources: requests 1 CPU / 2Gi, limits 4 CPU / 8Gi
- Env vars from ConfigMap + secretKeyRef (Vault-injected)
- Readiness probe: GET /health
- Liveness probe: GET /health
- Strategy: RollingUpdate, maxSurge: 1, maxUnavailable: 0 (zero-downtime)
- PodDisruptionBudget: minAvailable: 2

Celery Worker Deployment:
- command: celery -A apps.api.tasks worker --concurrency=4 --loglevel=info
- replicas HPA: min 2, max 8, scale on CPU > 60% or custom metric: celery_queue_length > 10
- resources: requests 2 CPU / 4Gi, limits 8 CPU / 16Gi

Celery Beat Deployment (single replica only):
- command: celery -A apps.api.tasks beat --loglevel=info
- replicas: 1 (never scale)
- No HPA — Beat must be a singleton

TASK 4 — Create Helm chart: infra/helm/stock-analyst-ml/
Chart for ML services on the GPU node:
  templates/
    ollama/deployment.yaml, service.yaml
    embedding-job/job.yaml  (runs once to pull model)
    reranker/deployment.yaml, service.yaml

Ollama Deployment:
- image: ollama/ollama:latest
- nodeSelector: role=ml
- resources: requests 8 CPU / 32Gi + nvidia.com/gpu: 1, limits 16 CPU / 64Gi + nvidia.com/gpu: 1
- volumeMounts: /root/.ollama from PVC (model storage, 500Gi)
- livenessProbe: GET http://localhost:11434/ (returns 200 if running)
- postStart hook: ollama pull nomic-embed-text:v1.5

Reranker Deployment:
- Custom image that loads cross-encoder/ms-marco-MiniLM-L-6-v2 at startup
- Exposes HTTP endpoint: POST /rerank { "query": str, "texts": [str] } → [float]
- resources: requests 2 CPU / 8Gi (runs on GPU node but doesn't need GPU for MiniLM)

TASK 5 — Create Helm chart: infra/helm/stock-analyst-infra/
Chart for Traefik, Vault CSI, LiteLLM:
  templates/
    litellm/deployment.yaml, service.yaml, configmap.yaml
    vault-csi/csp.yaml  (SecretProviderClass for each service's secrets)

LiteLLM ConfigMap: contains the config.yaml (model definitions, router settings)
The ANTHROPIC_API_KEY and OPENAI_API_KEY are injected from Vault via CSI driver:
  - SecretProviderClass for litellm referencing vault secrets path: secret/stock-analyst/llm-keys

Traefik IngressRoute (using Traefik CRD):
  - Host: api.stock-analyst.internal → stock-analyst-api service port 8000
  - Host: app.stock-analyst.internal → stock-analyst-web service port 3000
  - Host: auth.stock-analyst.internal → keycloak service port 8080
  - TLS: certResolver: internal-ca (Traefik cert-manager integration)
  - Middleware: rate limiting (100 req/s per IP), security headers

TASK 6 — Create Helm chart: infra/helm/stock-analyst-obs/
Monitoring stack:
  templates/
    prometheus/deployment.yaml, service.yaml, configmap.yaml (scrape configs)
    grafana/deployment.yaml, service.yaml, pvc.yaml, dashboards-configmap.yaml
    loki/deployment.yaml, service.yaml, pvc.yaml
    uptime-kuma/deployment.yaml, service.yaml, pvc.yaml

Prometheus scrape configs:
- fastapi metrics: /metrics endpoint on api service
- celery metrics: flower exporter
- qdrant metrics: /metrics on qdrant service
- node exporter: per-node system metrics

Grafana dashboards (as ConfigMap):
- Stock Analyst Overview: citation_coverage_rate, hallucination_rate, avg_retries, active_tasks
- Performance: ingestion_latency_p95, retrieval_latency_p95, agent_e2e_latency
- Cost: llm_tokens_per_hour by model, estimated_cost_per_tenant
- Infrastructure: CPU/memory/disk per node, Qdrant vector count, PostgreSQL size

TASK 7 — Create infra/k8s/scripts/bootstrap.sh:
Full cluster bootstrap script:
#!/bin/bash
set -e

echo "=== Stock Analyst AI — Cluster Bootstrap ==="

# 1. Apply namespaces
kubectl apply -f infra/k8s/namespaces/

# 2. Install Vault (must be first — other services need secrets)
helm upgrade --install vault infra/helm/stock-analyst-vault -n stock-analyst-infra --wait

# 3. Initialize Vault (interactive — operator must unseal and configure)
echo "=== MANUAL STEP: Initialize and unseal Vault, then configure AppRole and secrets ==="
echo "Run: vault operator init && vault operator unseal && ./scripts/configure_vault.sh"
read -p "Press ENTER when Vault is configured and sealed..."

# 4. Install data services (stateful — must be up before app)
helm upgrade --install data infra/helm/stock-analyst-data -n stock-analyst-data --wait --timeout 5m

# 5. Run DB migrations
kubectl create job --from=cronjob/db-migrate initial-migrate-$(date +%s) -n stock-analyst
kubectl wait --for=condition=complete job/initial-migrate-* -n stock-analyst --timeout=120s

# 6. Install ML services
helm upgrade --install ml infra/helm/stock-analyst-ml -n stock-analyst-ml --wait --timeout 10m

# 7. Install app services
helm upgrade --install app infra/helm/stock-analyst-app -n stock-analyst --wait

# 8. Install infra services (Traefik routes, LiteLLM)
helm upgrade --install infra-svc infra/helm/stock-analyst-infra -n stock-analyst-infra --wait

# 9. Install observability
helm upgrade --install obs infra/helm/stock-analyst-obs -n stock-analyst-obs --wait

# 10. Run MinIO setup
kubectl exec -n stock-analyst-data deploy/minio -- mc mb local/models
kubectl exec -n stock-analyst-data deploy/minio -- python /scripts/setup_minio.py

echo "=== Bootstrap complete. Run health check: curl https://api.stock-analyst.internal/health/deep ==="

CONSTRAINTS:
- All Helm values with secrets must use secretKeyRef or Vault CSI — never hardcode in values.yaml
- The Celery Beat deployment MUST have replicas: 1 and no HPA — multiple Beat instances would double-schedule jobs
- PVC storageClass must be "local-path" (k3s built-in) and all data-service PVCs must have nodeAffinity for the data node
- The init container that runs alembic migrations must wait for PostgreSQL to be ready (use wait-for-it.sh pattern)
- GPU scheduling: Ollama deployment must request nvidia.com/gpu: 1 and the GPU node must have the NVIDIA device plugin DaemonSet installed before deploying

ACCEPTANCE CRITERIA:
1. kubectl apply -f infra/k8s/namespaces/ creates all 5 namespaces
2. helm install data infra/helm/stock-analyst-data -n stock-analyst-data → all 4 data services Running
3. PostgreSQL PVC has storageClass=local-path and nodeAffinity for data node
4. helm install app infra/helm/stock-analyst-app → FastAPI API healthy at /health
5. Traefik routes traffic to correct services based on hostname
6. Grafana dashboard shows agent quality metrics after 5 minutes of synthetic traffic
```

---

## PROMPT 4.2 — HashiCorp Vault, Velero Backup & Security Audit

```
You are implementing secrets management, disaster recovery, and security hardening for the Stock Analyst AI platform.
The k3s cluster and all Helm charts from the previous step are in place.
Working directory: infra/

TASK 1 — Create infra/vault/configure_vault.sh:
Script that configures Vault after initial initialization and unseal:

#!/bin/bash
# Run AFTER: vault operator init && vault operator unseal

# 1. Enable KV secrets engine
vault secrets enable -path=secret kv-v2

# 2. Create secrets for each service
vault kv put secret/stock-analyst/llm-keys \
  ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
  OPENAI_API_KEY="${OPENAI_API_KEY}" \
  TAVILY_API_KEY="${TAVILY_API_KEY}"

vault kv put secret/stock-analyst/database \
  POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
  POSTGRES_USER="stockanalyst"

vault kv put secret/stock-analyst/storage \
  MINIO_ROOT_USER="${MINIO_ROOT_USER}" \
  MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD}"

vault kv put secret/stock-analyst/auth \
  KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD}" \
  KEYCLOAK_CLIENT_SECRET="${KEYCLOAK_CLIENT_SECRET}" \
  SECRET_KEY="${SECRET_KEY}"

vault kv put secret/stock-analyst/langsmith \
  LANGSMITH_API_KEY="${LANGSMITH_API_KEY}"

# 3. Enable AppRole auth for Kubernetes service accounts
vault auth enable approle

# 4. Create policy for the application
vault policy write stock-analyst-policy - <<EOF
path "secret/data/stock-analyst/*" {
  capabilities = ["read", "list"]
}
EOF

# 5. Create AppRole with policy
vault write auth/approle/role/stock-analyst \
  token_policies="stock-analyst-policy" \
  token_ttl=1h \
  token_max_ttl=4h

# 6. Enable Kubernetes auth (for CSI driver)
vault auth enable kubernetes
vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc"

vault write auth/kubernetes/role/stock-analyst \
  bound_service_account_names="stock-analyst-sa" \
  bound_service_account_namespaces="stock-analyst,stock-analyst-data,stock-analyst-ml,stock-analyst-infra" \
  policies="stock-analyst-policy" \
  ttl=1h

echo "Vault configured. Test with: vault kv get secret/stock-analyst/llm-keys"

TASK 2 — Create SecretProviderClass manifests for Vault CSI:
infra/k8s/vault/secret-provider-api.yaml:
Creates secrets for FastAPI pods via CSI driver:

apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: stock-analyst-api-secrets
  namespace: stock-analyst
spec:
  provider: vault
  parameters:
    vaultAddress: "http://vault.stock-analyst-infra.svc:8200"
    roleName: "stock-analyst"
    objects: |
      - objectName: "ANTHROPIC_API_KEY"
        secretPath: "secret/data/stock-analyst/llm-keys"
        secretKey: "ANTHROPIC_API_KEY"
      - objectName: "OPENAI_API_KEY"
        secretPath: "secret/data/stock-analyst/llm-keys"
        secretKey: "OPENAI_API_KEY"
      - objectName: "POSTGRES_PASSWORD"
        secretPath: "secret/data/stock-analyst/database"
        secretKey: "POSTGRES_PASSWORD"
      - objectName: "KEYCLOAK_CLIENT_SECRET"
        secretPath: "secret/data/stock-analyst/auth"
        secretKey: "KEYCLOAK_CLIENT_SECRET"
      - objectName: "SECRET_KEY"
        secretPath: "secret/data/stock-analyst/auth"
        secretKey: "SECRET_KEY"
  secretObjects:
  - secretName: stock-analyst-api-env
    type: Opaque
    data:
    - objectName: "ANTHROPIC_API_KEY"
      key: ANTHROPIC_API_KEY
    - objectName: "OPENAI_API_KEY"
      key: OPENAI_API_KEY
    (... etc for all secrets)

Create similar SecretProviderClass for: litellm, keycloak, postgres, minio.

TASK 3 — Create Velero backup configuration:
infra/k8s/backup/velero-schedule.yaml:

apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: daily-full-backup
  namespace: velero
spec:
  schedule: "0 2 * * *"  # 2am daily
  template:
    includedNamespaces:
    - stock-analyst
    - stock-analyst-data
    - stock-analyst-ml
    - stock-analyst-infra
    storageLocation: minio-backup
    volumeSnapshotLocations:
    - minio-backup
    ttl: 720h0m0s  # 30 days retention
    hooks:
      resources:
      - name: postgres-backup-hook
        includedNamespaces: [stock-analyst-data]
        labelSelector:
          matchLabels:
            app: postgres
        pre:
        - exec:
            container: postgres
            command: ["/bin/sh", "-c", "pg_dump -U stockanalyst stockanalyst > /tmp/backup.sql"]
            onError: Fail
            timeout: 5m

infra/k8s/backup/backup-storage-location.yaml:
Configure Velero to use a separate MinIO instance (or bucket) for backup storage:
  provider: aws  # Velero uses S3-compatible protocol
  objectStorage:
    bucket: velero-backups
    prefix: k3s-cluster
  config:
    region: us-east-1
    s3ForcePathStyle: "true"
    s3Url: "http://minio-backup.stock-analyst-data.svc:9000"

TASK 4 — Create security audit checklist script infra/scripts/security_audit.sh:
An automated pre-deployment security check that runs and produces a report:

#!/bin/bash
echo "=== Stock Analyst AI Security Audit ==="
PASS=0; FAIL=0; WARN=0

check() {
  local name="$1"; local cmd="$2"; local expected="$3"
  if eval "$cmd" | grep -q "$expected"; then
    echo "  PASS: $name"; ((PASS++))
  else
    echo "  FAIL: $name"; ((FAIL++))
  fi
}

echo "--- A01: Access Control ---"
# Test: tenant-a JWT cannot access tenant-b's coverage
check "cross-tenant API blocked" \
  'curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TENANT_A_JWT" $API_URL/coverages/$TENANT_B_COVERAGE_ID' \
  "403\|404"

# Test: RLS blocks cross-tenant DB access  
check "RLS enforced in PostgreSQL" \
  'psql -U stockanalyst -c "SET app.current_tenant_id='"'"'$TENANT_A_ID'"'"'; SELECT count(*) FROM coverages WHERE tenant_id='"'"'$TENANT_B_ID'"'"';" | grep -E "^ 0$"' \
  "0"

# Test: Qdrant cross-tenant search returns zero
check "Qdrant tenant isolation" \
  'python -c "from packages.rag.retrieval.hybrid_retriever import HybridRetriever; ..."' \
  "0 results"

echo "--- A02: Cryptographic Failures ---"
check "TLS enforced on all endpoints" \
  'curl -s -o /dev/null -w "%{http_code}" http://api.stock-analyst.internal/health' \
  "301\|308"  # should redirect to HTTPS

check "No secrets in env" \
  'kubectl get pods -n stock-analyst -o jsonpath="{.items[*].spec.containers[*].env[*].value}" | grep -v "ANTHROPIC\|OPENAI"' \
  ""  # no hardcoded keys found

echo "--- A03: Injection ---"
check "SQL injection blocked in search" \
  'curl -s -X POST $API_URL/coverages/$TEST_COVERAGE_ID/search -H "Authorization: Bearer $TEST_JWT" -d '"'"'{"q": "'"'"'; DROP TABLE coverages; --'"'"'"}'"'"' | grep -v "error"' \
  "results\|\[\]"

echo "--- A04: Audit log immutability ---"
check "audit log DELETE blocked" \
  'psql -U stockanalyst -c "DELETE FROM agent_audit_log LIMIT 1;" 2>&1' \
  "ERROR\|permission denied"

check "audit log UPDATE blocked" \
  'psql -U stockanalyst -c "UPDATE agent_audit_log SET action='"'"'modified'"'"' WHERE id=(SELECT id FROM agent_audit_log LIMIT 1);" 2>&1' \
  "ERROR\|permission denied"

echo "--- A09: Logging ---"
check "auth failures logged to Loki" \
  'curl -s "http://loki.stock-analyst-obs.svc:3100/loki/api/v1/query?query={app=\"stock-analyst-api\"}&level=warning" | grep auth_failure | wc -l' \
  "[1-9]"  # at least 1 auth failure log entry exists

echo "--- SSRF: fetch_url allowlist ---"
check "SSRF blocked for non-allowlisted domain" \
  'python -c "from packages.agents.industry_analyst.tools import fetch_url; import asyncio; asyncio.run(fetch_url('"'"'http://169.254.169.254/latest/meta-data/'"'"'))" 2>&1' \
  "ValueError\|not in allowlist"

echo "=== AUDIT RESULT: $PASS passed, $FAIL failed, $WARN warnings ==="
if [ $FAIL -gt 0 ]; then exit 1; fi

TASK 5 — Create docs/disaster-recovery.md:
Write the disaster recovery runbook with these scenarios (each must have: Symptoms, Steps, Verification):

1. Pod Crash Loop (auto-recovered by k8s — document monitoring signal only)
2. App Worker Node Failure (reschedule pods, add replacement node)
3. PostgreSQL Data Corruption:
   - Stop the postgres pod
   - velero restore --from-backup <latest-backup> --include-resources persistentvolumeclaims
   - Restart postgres with restored PVC
   - Verify: psql -c "SELECT count(*) FROM coverages"
4. Full Cluster Loss:
   - Provision new k3s cluster (4 nodes as before)
   - Install Velero with same backup storage config
   - velero restore --from-backup <latest-backup>
   - Re-initialize Vault (new unseal keys) and re-inject secrets
   - Estimated RTO: 4 hours
5. Qdrant Vector Store Corruption:
   - Delete Qdrant PVC and recreate
   - Re-run ingest_document_task for all documents in DB (storage_path in MinIO is intact)
   - Use script: python scripts/reindex_all.py --coverage-id {id}
6. LLM API Key Compromise:
   - vault kv put secret/stock-analyst/llm-keys ANTHROPIC_API_KEY={new_key}
   - kubectl rollout restart deployment/stock-analyst-api -n stock-analyst
   - Invalidate old key at Anthropic console

CONSTRAINTS:
- Vault must be initialized with 5 key shares, 3 required to unseal (production-grade Shamir secret sharing)
- Velero backup must include volume snapshots (not just etcd) — the actual data is in PVCs
- The security audit script must exit with code 1 if any FAIL occurs — used as a CI gate
- docs/disaster-recovery.md must specify the EXACT commands, not just "restore from backup" — operators run this under stress

ACCEPTANCE CRITERIA:
1. vault kv get secret/stock-analyst/llm-keys returns the API keys
2. FastAPI pod reads ANTHROPIC_API_KEY from CSI-mounted secret (not from values.yaml)
3. Velero schedule created; velero backup get shows a backup completed within 24 hours
4. security_audit.sh runs with 0 FAIL (after setting test variables)
5. Deliberate DELETE on agent_audit_log → blocked, audit script reports PASS for this check
6. DR runbook: full cluster restore tested on a staging cluster; RTO documented
```

---

## PROMPT TEST.1 — Comprehensive Test Suite Setup

```
You are implementing the complete test suite for the Stock Analyst AI platform.
All phases are complete. This prompt sets up test infrastructure and fills in missing test coverage.
Working directory: tests/

CONTEXT:
The test suite has three tiers:
- tests/unit/: Fast, no external services, all mocked. Run on every commit.
- tests/integration/: Real services (Docker Compose), slower. Run on PR merge.
- tests/e2e/: Full user flows via Playwright. Run nightly and pre-release.

TASK 1 — Create tests/conftest.py:
Shared pytest fixtures:

import pytest, asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
import pytest_asyncio

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
def test_tenant_a_id():
    return "00000000-0000-0000-0000-000000000001"

@pytest.fixture(scope="session")
def test_tenant_b_id():
    return "00000000-0000-0000-0000-000000000002"

@pytest_asyncio.fixture(scope="session")
async def db_session():
    engine = create_async_engine(settings.DATABASE_URL.replace("+asyncpg", "+asyncpg"))
    async with AsyncSession(engine) as session:
        # Set tenant context for tests
        await session.execute(text("SET app.current_tenant_id = '00000000-0000-0000-0000-000000000001'"))
        yield session

@pytest_asyncio.fixture
async def api_client(test_tenant_a_jwt):
    from apps.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.headers["Authorization"] = f"Bearer {test_tenant_a_jwt}"
        yield client

@pytest.fixture
def mock_llm_response():
    # Returns a factory that creates consistent mock LLM responses
    def factory(content: str, model: str = "claude-sonnet-4-6", tokens: int = 500):
        class MockResponse:
            class choices:
                class _item:
                    class message:
                        pass
                _item.message.content = content
            choices = [_item()]
            class usage:
                total_tokens = tokens
            model = model
        return MockResponse()
    return factory

@pytest.fixture
def mock_retriever():
    # Mock HybridRetriever that returns synthetic chunks
    from unittest.mock import AsyncMock, MagicMock
    retriever = AsyncMock()
    
    def make_chunk(content: str, doc_name: str = "AAPL 10-K 2023", 
                   section: str = "Business", chunk_id: str = None):
        from packages.rag.retrieval.hybrid_retriever import RetrievedChunk
        import uuid
        return RetrievedChunk(
            chunk_id=chunk_id or str(uuid.uuid4()),
            content=content,
            metadata={"document_name": doc_name, "section_name": section,
                     "tenant_id": "00000000-0000-0000-0000-000000000001",
                     "coverage_id": "test-coverage-id", "page_number": 1,
                     "filing_type": "10-K", "period": "FY2023"},
            score=0.92,
            parent_content=f"[Parent context for: {content[:50]}]",
            parent_chunk_id=str(uuid.uuid4()),
        )
    
    retriever.retrieve.return_value = [
        make_chunk('Revenue was $383.3 billion for fiscal year 2023'),
        make_chunk('Gross margin was 44.1%, up from 43.3% in fiscal 2022'),
        make_chunk('The Company had $29.9 billion in cash and marketable securities'),
    ]
    retriever.retrieve_exact_quote.return_value = make_chunk(
        'Revenue was $383.3 billion for fiscal year 2023'
    )
    retriever.make_chunk = make_chunk  # helper for custom test data
    return retriever

TASK 2 — Create comprehensive integration test: tests/integration/test_full_workflow.py
This tests the complete happy path from document upload through approved bull case:

@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_coverage_workflow(api_client, db_session):
    # Step 1: Create coverage
    resp = await api_client.post("/api/v1/coverages", json={
        "ticker": "MSFT", "company_name": "Microsoft Corporation",
        "exchange": "NASDAQ", "industry_name": "Enterprise Software"
    })
    assert resp.status_code == 201
    coverage_id = resp.json()["coverage_id"]
    
    # Step 2: Upload a 10-K (use a real small 10-K from eval fixtures)
    with open("eval/fixtures/msft_10k_2023_abridged.pdf", "rb") as f:
        resp = await api_client.post(
            f"/api/v1/coverages/{coverage_id}/documents",
            files={"file": ("msft_10k_2023.pdf", f, "application/pdf")},
            data={"filing_type": "10-K", "period": "FY2023", "source": "user_upload"}
        )
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]
    
    # Step 3: Wait for ingestion to complete
    for _ in range(60):  # up to 120 seconds (2s * 60)
        await asyncio.sleep(2)
        status_resp = await api_client.get(f"/api/v1/tasks/{task_id}")
        if status_resp.json()["status"] == "completed":
            break
    assert status_resp.json()["status"] == "completed", "Ingestion did not complete in 120s"
    
    # Step 4: Verify chunks in Qdrant
    doc_resp = await api_client.get(f"/api/v1/coverages/{coverage_id}/documents")
    doc = doc_resp.json()[0]
    assert doc["ingest_status"] == "indexed"
    assert doc["chunk_count"] > 100, "Expected >100 chunks from a real 10-K"
    
    # Step 5: Run Lynch Pitch
    pitch_resp = await api_client.post(
        f"/api/v1/coverages/{coverage_id}/tasks/lynch-pitch", json={}
    )
    assert pitch_resp.status_code == 202
    pitch_task_id = pitch_resp.json()["task_id"]
    
    # Step 6: Wait for Lynch Pitch (up to 120 seconds)
    for _ in range(60):
        await asyncio.sleep(2)
        status = (await api_client.get(f"/api/v1/tasks/{pitch_task_id}")).json()
        if status["status"] in ("completed", "failed"):
            break
    assert status["status"] == "completed"
    
    # Step 7: Verify output in research_outputs
    outputs_resp = await api_client.get(f"/api/v1/coverages/{coverage_id}/outputs")
    lynch_outputs = [o for o in outputs_resp.json() if o["output_type"] == "lynch_pitch"]
    assert len(lynch_outputs) == 1
    output = lynch_outputs[0]
    assert output["approved_by_enforcer"] == True
    assert output["citation_coverage_pct"] >= 0.95
    assert output["enforcer_status"] == "approved"
    
    # Step 8: Verify all 8 questions answered
    content = output["content"]
    for q_num in range(1, 9):
        assert f"### Q{q_num}:" in content, f"Q{q_num} missing from output"

TASK 3 — Create cross-tenant isolation integration test: tests/integration/test_tenant_isolation.py

@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_cross_tenant_blocked(api_client_tenant_a, api_client_tenant_b, 
                                        tenant_a_coverage_id):
    # Tenant B's client tries to access Tenant A's coverage
    resp = await api_client_tenant_b.get(f"/api/v1/coverages/{tenant_a_coverage_id}")
    assert resp.status_code in (403, 404), f"Cross-tenant API access not blocked: {resp.status_code}"

@pytest.mark.integration
@pytest.mark.asyncio
async def test_qdrant_cross_tenant_zero_results(test_tenant_a_id, test_tenant_b_id,
                                                  tenant_a_coverage_id, retriever):
    # Search Tenant A's data using Tenant B's tenant_id
    results = await retriever.retrieve(
        query="revenue gross margin",
        tenant_id=test_tenant_b_id,  # WRONG tenant
        coverage_id=tenant_a_coverage_id  # Tenant A's coverage
    )
    assert len(results) == 0, f"Expected 0 results, got {len(results)} — TENANT ISOLATION BREACH"

@pytest.mark.integration
@pytest.mark.asyncio  
async def test_rls_direct_sql(db_session, test_tenant_a_id, test_tenant_b_id):
    # Set tenant context to tenant A
    await db_session.execute(text(f"SET app.current_tenant_id = '{test_tenant_a_id}'"))
    
    # Try to fetch tenant B's coverages
    result = await db_session.execute(
        text("SELECT count(*) FROM coverages WHERE tenant_id = :tid"),
        {"tid": test_tenant_b_id}
    )
    count = result.scalar()
    assert count == 0, f"RLS failed: tenant A session returned {count} tenant B rows"

TASK 4 — Create E2E test with Playwright: tests/e2e/test_analyst_workflow.py

import pytest
from playwright.async_api import async_playwright, Page

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_analyst_login_and_coverage_creation():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Login
        await page.goto("http://localhost:3000")
        await page.click("text=Sign in with your organization")
        # Keycloak login form
        await page.fill("#username", "analyst-a@test.com")
        await page.fill("#password", "TestPass123!")
        await page.click('input[type="submit"]')
        await page.wait_for_url("**/coverages")
        
        # Create new coverage
        await page.click("text=New Coverage")
        await page.fill('[placeholder*="ticker"]', "NVDA")
        await page.fill('[placeholder*="company"]', "NVIDIA Corporation")
        await page.select_option('[name="exchange"]', "NASDAQ")
        await page.click("text=Create Coverage")
        await page.wait_for_url("**/coverages/**")
        
        # Should be on documents page
        assert "documents" in page.url
        
        await browser.close()

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_document_upload_and_ingestion_status(page: Page):
    # Upload a PDF
    await page.click("text=Upload Document")
    await page.set_input_files('[data-testid="file-input"]', "eval/fixtures/test_10k.pdf")
    await page.select_option('[name="filing_type"]', "10-K")
    await page.fill('[name="period"]', "FY2023")
    await page.click("text=Upload")
    
    # Wait for status badge to change from Queued → Indexing → Indexed
    await page.wait_for_selector('[data-status="indexed"]', timeout=150_000)  # 2.5 min
    
    # Verify chunk count is shown
    chunk_count = await page.text_content('[data-testid="chunk-count"]')
    assert int(chunk_count) > 0

TASK 5 — Create load test: tests/load/locustfile.py

from locust import HttpUser, task, between

class AnalystUser(HttpUser):
    wait_time = between(1, 5)
    
    def on_start(self):
        # Login and get JWT
        resp = self.client.post("/api/auth/token", 
                                json={"username": "analyst-a@test.com", "password": "TestPass123!"})
        self.headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        # Use a pre-existing coverage with documents indexed
        self.coverage_id = "load-test-coverage-id"
    
    @task(3)
    def list_coverages(self):
        self.client.get("/api/v1/coverages", headers=self.headers)
    
    @task(3)
    def list_documents(self):
        self.client.get(f"/api/v1/coverages/{self.coverage_id}/documents", headers=self.headers)
    
    @task(2)
    def search_coverage(self):
        self.client.post(f"/api/v1/coverages/{self.coverage_id}/search",
                         json={"q": "gross margin revenue growth"},
                         headers=self.headers)
    
    @task(1)
    def view_kpis(self):
        self.client.get(f"/api/v1/coverages/{self.coverage_id}/kpis", headers=self.headers)
    
    @task(1)  
    def view_outputs(self):
        self.client.get(f"/api/v1/coverages/{self.coverage_id}/outputs", headers=self.headers)

# Run with: locust -f tests/load/locustfile.py --headless -u 10 -r 2 --run-time 5m --host http://localhost:8000
# Target: all tasks complete with p95 < 500ms; 0% error rate

CONSTRAINTS:
- Integration tests must be skipped in unit test runs (mark with @pytest.mark.integration)
- E2E tests require a full running stack — mark with @pytest.mark.e2e and skip unless --e2e flag passed
- The load test locustfile must work with 10 concurrent users targeting the NFR-PERF targets
- conftest.py must not import any production code at module level — only inside fixtures — to allow unit tests to run without full stack

ACCEPTANCE CRITERIA:
1. pytest tests/unit/ → all pass, <3 minutes
2. pytest tests/integration/ -m integration → all pass including cross-tenant isolation
3. pytest tests/e2e/ -m e2e → login, create coverage, upload document flows complete
4. locust load test: 10 users, 5 minutes → p95 < 500ms for all tasks, 0% error rate
5. The full CI pipeline (lint + unit + migration + eval-gate) completes in <15 minutes
```
