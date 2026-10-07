"""Who may do what. The single table every service consults, so a role rule cannot be
forgotten by one route. Admin manages users and nothing on a deal; walls bind everyone."""
from enum import Enum

from aura.core.domain.enums import HandoffTrigger, Role
from aura.core.domain.errors import Forbidden


class Capability(str, Enum):
    CREATE_DEAL = "create_deal"
    EDIT_DEAL_DATA = "edit_deal_data"          # documents, diligence, conditions, findings,
    SUBMIT_JOB = "submit_job"                  # parties, mandates; and running agent jobs
    TRANSITION_DEAL = "transition_deal"
    # Move a deal only by overriding guards that name this role (see transition_deal).
    OVERRIDE_OWN_GUARDS = "override_own_guards"
    RESOLVE_HANDOFF = "resolve_handoff"
    RESOLVE_POLICY_HANDOFF = "resolve_policy_handoff"
    MANAGE_WALL = "manage_wall"
    SIGN_OFF = "sign_off"
    EDIT_REGULATORY_FLAGS = "edit_regulatory_flags"
    VERIFY_EXTRACTION = "verify_extraction"
    MANAGE_USERS = "manage_users"
    MANAGE_AUTONOMY = "manage_autonomy"        # promote a demoted capability
    # Outbound email (migration 0013).
    VIEW_CONTACTS = "view_contacts"
    MANAGE_CONTACTS = "manage_contacts"        # add and remove a party's email contacts
    VERIFY_CONTACT = "verify_contact"          # vouch that an address really is the party's
    MANAGE_SUPPRESSION = "manage_suppression"  # the do-not-contact list
    VIEW_INTEGRATIONS = "view_integrations"    # Gmail connection status (never a token)


_C = Capability
_DEAL_WORK = {_C.CREATE_DEAL, _C.EDIT_DEAL_DATA, _C.SUBMIT_JOB, _C.VERIFY_EXTRACTION,
              _C.VIEW_CONTACTS, _C.MANAGE_CONTACTS}

_GRANTS: dict[Role, frozenset[Capability]] = {
    Role.ADMIN: frozenset({_C.MANAGE_USERS, _C.MANAGE_AUTONOMY, _C.VIEW_INTEGRATIONS}),
    Role.DEALMAKER: frozenset(_DEAL_WORK | {_C.TRANSITION_DEAL, _C.RESOLVE_HANDOFF,
                                            _C.EDIT_REGULATORY_FLAGS, _C.VERIFY_CONTACT,
                                            _C.MANAGE_SUPPRESSION, _C.VIEW_INTEGRATIONS}),
    Role.ANALYST: frozenset(_DEAL_WORK),
    Role.COMPLIANCE: frozenset({_C.RESOLVE_POLICY_HANDOFF, _C.MANAGE_WALL, _C.SIGN_OFF,
                                _C.EDIT_REGULATORY_FLAGS, _C.OVERRIDE_OWN_GUARDS,
                                _C.VIEW_CONTACTS, _C.MANAGE_SUPPRESSION}),
}


def check_transition_actor(role: Role, justification: str,
                           failing_blocking_override_roles: list[str | None]) -> None:
    """Who may perform a stage move, given the blocking guards that failed for it.

    A dealmaker always may (guards still apply). A role holding OVERRIDE_OWN_GUARDS (compliance)
    may only as an override: it gives a justification, at least one blocking guard failed, and
    every failing blocking guard names that role. It cannot make an ordinary move."""
    if can(role, Capability.TRANSITION_DEAL):
        return
    if (can(role, Capability.OVERRIDE_OWN_GUARDS) and justification
            and failing_blocking_override_roles
            and all(r == role.value for r in failing_blocking_override_roles)):
        return
    if can(role, Capability.OVERRIDE_OWN_GUARDS):
        raise Forbidden(f"The {role.value} role cannot move a deal between stages except to "
                        f"override, with a justification, guards that name {role.value}")
    raise Forbidden(f"The {role.value} role cannot move a deal between stages")


def can(role: Role, capability: Capability) -> bool:
    return capability in _GRANTS.get(role, frozenset())


def require(role: Role, capability: Capability, what: str = "") -> None:
    """Raise Forbidden (403) unless the role holds the capability."""
    if not can(role, capability):
        raise Forbidden(f"The {role.value} role cannot {what or capability.value.replace('_', ' ')}")


def can_resolve_handoff(role: Role, trigger: HandoffTrigger) -> bool:
    """Dealmakers resolve any handoff; compliance also resolves policy-required ones."""
    return can(role, Capability.RESOLVE_HANDOFF) or (
        trigger is HandoffTrigger.POLICY_REQUIRED
        and can(role, Capability.RESOLVE_POLICY_HANDOFF))


def require_any_resolve_handoff(role: Role) -> None:
    """Roles that can resolve no handoff at all are refused before anything is looked up."""
    if not (can(role, Capability.RESOLVE_HANDOFF)
            or can(role, Capability.RESOLVE_POLICY_HANDOFF)):
        raise Forbidden(f"The {role.value} role cannot resolve handoffs")


def require_resolve_handoff(role: Role, trigger: HandoffTrigger) -> None:
    if not can_resolve_handoff(role, trigger):
        raise Forbidden(f"The {role.value} role cannot resolve a {trigger.value} handoff")
