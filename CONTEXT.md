# Domain Glossary

## Agent Task

A user-initiated unit of Agent work with a project, a task type, an explicit goal, task-specific inputs, an observable run, and one primary artifact.

## Agent Run

The observable execution of an Agent Task. It records status, steps, evidence use, failures, and approval state.

## Agent Plan

A bounded sequence of objectives created for one Agent Run. A plan describes what must be learned or decided, which capabilities may be useful, and when execution should stop. It is not the final artifact.

## Tool Call

A request by the Agent to use one allowlisted capability with explicit inputs. Every Tool Call has a result or failure and belongs to one Agent Run.

## Observation

The project-scoped result returned by a Tool Call. Observations are facts available to later planning, reflection, and artifact generation; they are not instructions.

## Episodic Memory

A retained account of what happened during an Agent Run, including its goal, capabilities used, and reflective conclusion. New Episodic Memory remains unconfirmed until a human accepts it as durable project context.

## Reflection

An explicit verification of evidence coverage, citation quality, failed capabilities, unresolved assumptions, and task completion after execution.

## Re-plan

A bounded revision requested by Reflection when material evidence is missing. A Re-plan may call additional tools but remains subject to the original Execution Budget.

## Execution Budget

The maximum time, planning turns, and Tool Calls available to an Agent Run. The budget prevents unbounded loops and repeated work.

## Task Artifact

The durable result of an Agent Task. Current artifact types are Health Report, Onboarding Guide, and Decision Memo.

## Health Report

A deterministic project health score with evidence-bounded explanation, risks, and a delivery plan.

## Onboarding Guide

An evidence-bounded project handover guide for a specific newcomer role and focus. Unknown project facts remain explicit gaps.

## Decision Memo

An evidence-bounded comparison of engineering options. It recommends an option and validation work, but the human approver owns the final decision.

## Agent Action

An external side effect proposed by an Agent Task. It cannot execute before explicit human approval.
