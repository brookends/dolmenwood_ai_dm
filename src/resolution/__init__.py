"""
Dolmenwood AI DM - Resolution Layer (v2.0)

This package contains the action resolution and procedure trigger systems.
"""

from .action_resolver import (
    ActionResolver,
    Action,
    ActionResult,
    ActionType,
    FailureType,
    SuccessCostType,
    create_action_resolver,
    resolve_attack,
    resolve_save,
    resolve_skill_check,
)

from .procedure_triggers import (
    ProcedureTrigger,
    TriggerPriority,
    TriggerResult,
    TriggerHandler,
    ProcedureHandler,
    AutomaticTriggerChecker,
    create_trigger_handler,
)

__all__ = [
    # Action Resolver
    "ActionResolver",
    "Action",
    "ActionResult",
    "ActionType",
    "FailureType",
    "SuccessCostType",
    "create_action_resolver",
    "resolve_attack",
    "resolve_save",
    "resolve_skill_check",
    # Procedure Triggers
    "ProcedureTrigger",
    "TriggerPriority",
    "TriggerResult",
    "TriggerHandler",
    "ProcedureHandler",
    "AutomaticTriggerChecker",
    "create_trigger_handler",
]
