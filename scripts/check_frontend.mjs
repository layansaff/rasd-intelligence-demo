import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const html = await readFile(new URL("../frontend/index.html", import.meta.url), "utf8");
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/i);
assert.ok(scriptMatch, "the frontend must contain its application script");
const script = scriptMatch[1];
new vm.Script(script, { filename: "frontend/index.html" });

const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
assert.equal(new Set(ids).size, ids.length, "HTML ids must be unique");
for (const match of html.matchAll(/data-for="([^"]+)"/g)) {
  assert.ok(ids.includes(match[1]), `stepper target ${match[1]} must exist`);
}
for (const [id, minimum] of [["recovery", 0], ["required", 1]]) {
  const input = html.match(new RegExp(`<input id="${id}"[^>]+>`))?.[0];
  assert.ok(input, `${id} input must exist`);
  assert.match(input, /type="text"/);
  assert.match(input, /pattern="\[0-9\]\+"/);
  assert.match(input, /role="spinbutton"/);
  assert.match(input, new RegExp(`data-min="${minimum}"`));
  assert.match(input, /data-max="8760"/);
}
assert.match(script, /recovery_hours:Number\(\$\("#recovery"\)\.value\)/);
assert.match(script, /required_recovery_hours:Number\(\$\("#required"\)\.value\)/);
assert.match(script, /base:window\.location\.protocol==="file:"\?"http:\/\/127\.0\.0\.1:8000":window\.location\.origin/);
assert.match(script, /data\.demo_mode===true/);
assert.match(script, /Public portfolio demo: use fictional information only/);
assert.match(script, /if\(S\.demoMode\)all\.push\(\.\.\.S\.items\.map/);

const functionLine = (name) => {
  const start = script.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} must exist`);
  return script.slice(start, script.indexOf("\n", start));
};
const sandbox = {
  Number,
  String,
  Math,
  Event: class TestEvent {
    constructor(type, options) { this.type = type; this.options = options; }
  },
};
vm.createContext(sandbox);
vm.runInContext(
  `${functionLine("validateRecoveryField")};${functionLine("stepRecoveryField")}`,
  sandbox,
);

function makeField(value, min, max) {
  return {
    value: String(value),
    dataset: { min: String(min), max: String(max) },
    validityMessage: "",
    attributes: {},
    setCustomValidity(message) { this.validityMessage = message; },
    setAttribute(name, value) { this.attributes[name] = value; },
    dispatchEvent() {},
  };
}

const estimated = makeField(72, 0, 8760);
const required = makeField(24, 1, 8760);
assert.equal(sandbox.validateRecoveryField(estimated), true);
assert.equal(sandbox.validateRecoveryField(required), true);
sandbox.stepRecoveryField(estimated, 1);
sandbox.stepRecoveryField(required, -1);
assert.equal(estimated.value, "73");
assert.equal(required.value, "23");

const minimumZero = makeField(0, 0, 8760);
const minimumOne = makeField(1, 1, 8760);
const maximum = makeField(8760, 0, 8760);
sandbox.stepRecoveryField(minimumZero, -1);
sandbox.stepRecoveryField(minimumOne, -1);
sandbox.stepRecoveryField(maximum, 1);
assert.deepEqual([minimumZero.value, minimumOne.value, maximum.value], ["0", "1", "8760"]);

for (const [value, min, valid] of [
  ["0", 0, true], ["8760", 0, true], ["1", 1, true],
  ["8761", 0, false], ["0", 1, false], ["1.5", 0, false], ["", 0, false],
]) {
  assert.equal(sandbox.validateRecoveryField(makeField(value, min, 8760)), valid);
}

const conversionStart = script.indexOf("const western=field.value.replace");
assert.notEqual(conversionStart, -1, "input digit normalization must exist");
const conversionEnd = script.indexOf(";", conversionStart) + 1;
const conversion = script.slice(conversionStart, conversionEnd);
sandbox.field = { value: "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹" };
assert.equal(
  vm.runInContext(`${conversion} western`, sandbox),
  "01234567890123456789",
);

const recommendationSelection = script.match(/const rec=(.*?);\$\("#recommendations"\)/)?.[1];
assert.ok(recommendationSelection, "recommendations must be selected before rendering");
const recommendationContext = vm.createContext({
  d: {
    recommendations: ["Action A", "Action B"],
    recommendation: "Action A Action B",
  },
});
assert.deepEqual(
  Array.from(vm.runInContext(recommendationSelection, recommendationContext)),
  ["Action A", "Action B"],
  "the compatibility summary must not duplicate the recommendations list",
);
recommendationContext.d = { recommendations: [], recommendation: "Legacy action" };
assert.deepEqual(
  Array.from(vm.runInContext(recommendationSelection, recommendationContext)),
  ["Legacy action"],
  "older responses with only a single recommendation must still render",
);

console.log("Frontend checks passed: syntax, structure, western digits, bounds, steppers, numeric payloads, and recommendation rendering.");
