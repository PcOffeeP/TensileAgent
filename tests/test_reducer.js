const fs = require('fs');

// Simple test for reduceAgentEvent
// To run: node tests/test_reducer.js

const code = fs.readFileSync('web/src/hooks/useAgentTaskEvents.ts', 'utf8');

// A very hacky way to test typescript pure function from nodejs
// In a real project we would setup jest or vitest
const extractReducer = code.match(/export function reduceAgentEvent\([\s\S]*?\n\}/)[0];
const executable = extractReducer.replace('export function reduceAgentEvent', 'function reduceAgentEvent')
  .replace(/: AnalysisTrace/g, '')
  .replace(/: AgentEvent/g, '')
  .replace(/: any/g, '')
  .replace(/: string/g, '')
  .replace(/as FinalResult/g, '')
  .replace(/: AnalysisRound/g, '');

eval(executable);

let trace = {
  taskId: "t1",
  videoDurationSec: null,
  initialCandidate: null,
  rounds: [],
  finalResult: null,
  taskError: null,
  connectionState: "open",
  rawEvents: []
};

// Test round=0, round=1, round=2 + immutability + seq deduplication
const events = [
  { seq: 1, event: "round_started", data: { event_type: "round_started", round: 0, display_round: 1, state: "scan", candidate: [0, 100] } },
  { seq: 2, event: "round_started", data: { event_type: "round_started", round: 1, display_round: 2, state: "zoom", candidate: [20, 50] } },
  { seq: 3, event: "round_started", data: { event_type: "round_started", round: 2, display_round: 3, state: "verify", candidate: [30, 40] } },
];

for (const ev of events) {
  trace = reduceAgentEvent(trace, ev, ev.event, ev.data);
}

const beforeUpdateRounds = trace.rounds;
const beforeRound2 = trace.rounds[2];
const updated = reduceAgentEvent(
  trace,
  { seq: 4, event: "sample_and_infer_started", data: { event_type: "sample_and_infer_started", round: 2, sample_range: [30, 40] } },
  "sample_and_infer_started",
  { event_type: "sample_and_infer_started", round: 2, sample_range: [30, 40] }
);
const deduped = reduceAgentEvent(
  updated,
  { seq: 4, event: "sample_and_infer_started", data: { event_type: "sample_and_infer_started", round: 2, sample_range: [30, 40] } },
  "sample_and_infer_started",
  { event_type: "sample_and_infer_started", round: 2, sample_range: [30, 40] }
);

if (
  updated.rounds.length === 3 &&
  updated.rounds !== beforeUpdateRounds &&
  updated.rounds[2] !== beforeRound2 &&
  beforeRound2.sampleRange === undefined &&
  deduped === updated
) {
  console.log("PASS: 3 rounds created, immutable updates, seq deduplication verified");
  process.exit(0);
} else {
  console.error("FAIL: reducer invariant violated");
  process.exit(1);
}
