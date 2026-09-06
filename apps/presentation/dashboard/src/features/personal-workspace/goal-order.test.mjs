import assert from "node:assert/strict";
import { decodeGoalOrder, goalOrderStorageKey, moveGoal, orderedGoals } from "../../../node_modules/.cache/loopx-goal-order/goal-order.js";

assert.deepEqual(decodeGoalOrder('{'), []);
assert.deepEqual(decodeGoalOrder('["a", 1]'), []);
assert.deepEqual(decodeGoalOrder('["a","a","b"]'), ['a', 'b']);
const goals = ['a', 'b', 'c'].map(goalId => ({ goalId }));
assert.deepEqual(orderedGoals(goals, ['b', 'a']).map(g => g.goalId), ['b', 'a', 'c']);
assert.deepEqual(goals.map(g => g.goalId), ['a', 'b', 'c']);
assert.deepEqual(moveGoal([], ['a','b','c'], 'a', 'c', true), ['b','c','a']);
assert.deepEqual(moveGoal([], ['a','b','c'], 'c', 'a', false), ['c','a','b']);
assert.deepEqual(moveGoal(['a','stopped','b'], ['a','b','new'], 'b', 'a', false), ['b','a','stopped','new']);
assert.deepEqual(moveGoal(['a','b'], ['a','b'], 'missing', 'a', false), ['a','b']);
assert.deepEqual(moveGoal(['a','b'], ['a','b'], 'a', 'a', true), ['a','b']);
assert.notEqual(goalOrderStorageKey('/status.json'), goalOrderStorageKey('http://127.0.0.1:8877/status.json'));
console.log('Goal presentation order invariants passed');
