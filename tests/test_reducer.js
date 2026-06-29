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

// Test round=0, round=1, round=2
const events = [
  { event: "round_started", data: { event_type: "round_started", round: 0, display_round: 1, state: "scan", candidate: [0, 100] } },
  { event: "round_started", data: { event_type: "round_started", round: 1, display_round: 2, state: "zoom", candidate: [20, 50] } },
  { event: "round_started", data: { event_type: "round_started", round: 2, display_round: 3, state: "verify", candidate: [30, 40] } },
];

for (const ev of events) {
  trace = reduceAgentEvent(trace, ev, ev.event, ev.data);
}

if (trace.rounds.length === 3) {
  console.log("PASS: 3 rounds created");
  process.exit(0);
} else {
  console.error("FAIL: Expected 3 rounds, got " + trace.rounds.length);
  console.error(JSON.stringify(trace.rounds, null, 2));
  process.exit(1);
}
