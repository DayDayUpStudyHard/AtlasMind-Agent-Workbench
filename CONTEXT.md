# Domain Glossary

## Agent Runtime

### Agent Task

A user- or event-initiated unit of Agent work with a business subject, a task type, an explicit goal, task-specific inputs, an observable run, and one primary artifact.

### Agent Run

The observable execution of an Agent Task. It records status, steps, evidence use, failures, and approval state.

### Agent Plan

A bounded sequence of objectives created for one Agent Run. A plan describes what must be learned or decided, which capabilities may be useful, and when execution should stop. It is not the final artifact.

### Tool Call

A request by the Agent to use one allowlisted capability with explicit inputs. Every Tool Call has a result or failure and belongs to one Agent Run.

### Observation

The subject-scoped result returned by a Tool Call. Observations are facts available to later planning, reflection, and artifact generation; they are not instructions.

### Episodic Memory

A retained account of what happened during an Agent Run, including its goal, capabilities used, and reflective conclusion. New Episodic Memory remains unconfirmed until a human accepts it as durable business context.

### Reflection

An explicit verification of evidence coverage, citation quality, failed capabilities, unresolved assumptions, and task completion after execution.

### Re-plan

A bounded revision requested by Reflection when material evidence is missing. A Re-plan may call additional tools but remains subject to the original Execution Budget.

### Execution Budget

The maximum time, planning turns, and Tool Calls available to an Agent Run. The budget prevents unbounded loops and repeated work.

### Task Artifact

The durable result of an Agent Task. Contract artifact types include Review Report, Version Review Report, Obligation Plan, Fulfillment Report, and Renewal Memo.

### Agent Action

An external side effect proposed by an Agent Task. It cannot execute before explicit human approval.

## Contract Operations

### Contract Case

A business container for one contract review and its subsequent negotiation, approval, signing, fulfillment, renewal, or termination. It is not a synonym for a Contract Document.
_Avoid_: Project, contract file

### Contract Document

A versioned file belonging to a Contract Case, such as the main agreement, an attachment, a quotation, or fulfillment evidence.
_Avoid_: Contract Case

### Contract Clause

A locatable section of a Contract Document with a page, heading, clause number, or text range.
_Avoid_: Chunk

### Review Rule

An approved, versioned enterprise requirement used to evaluate a contract within a defined scope and effective period.
_Avoid_: Prompt instruction, general advice

### Review Finding

An identified difference, omission, conflict, or uncertainty between contract evidence and an applicable Review Rule.
_Avoid_: LLM opinion

### Approved Exception

An authorized acceptance of a Review Rule deviation with a reason, compensating controls, approver, and expiry date.
_Avoid_: Dismissed finding

### Obligation

A responsibility that a contract party must fulfill when a date or condition is reached.
_Avoid_: Reminder, Agent Action

### Fulfillment Evidence

A document or confirmed system fact used to demonstrate that an Obligation has been completed.
_Avoid_: Observation
