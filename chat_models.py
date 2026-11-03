"""Governed, explicit chat model choices; no credentials in public metadata."""
from codex_gateway import ModelPolicy, select_model
from gemini_gateway import load_gemini_config, gemini_enabled
from pathlib import Path


def manual_rules(registry):
    # Older versioned runtime snapshots predate explicit chat choices. Use the
    # committed additive policy only when the snapshot has no such field.
    if 'manual_chat_models' in registry.data:
        return registry.data['manual_chat_models']
    from veridex_governance import GovernanceRegistry
    committed = GovernanceRegistry(Path(__file__).resolve().parent / 'governance/navigator_governance_v1.0.0.json')
    return committed.data.get('manual_chat_models') or {}


def resolve_choice(registry, choice, task_type='conversation', attachments=False, reasoning=''):
    if not choice or choice == 'default':
        if reasoning:
            raise ValueError('Choose an explicit model to adjust reasoning')
        return None
    rule = manual_rules(registry).get(choice)
    if not rule:
        raise ValueError('Unknown chat model selection')
    if reasoning and reasoning not in rule.get('reasoning_options', []):
        raise ValueError('Unsupported reasoning level for this model')
    if rule.get('task_types') and task_type not in rule['task_types']:
        raise ValueError('This provider supports text conversation only; choose Default or a Codex model for this task')
    if rule['provider'] == 'gemini_api':
        if attachments:
            raise ValueError('Gemini chat does not support attachments; choose a Codex model')
        config = load_gemini_config()
        if not gemini_enabled(config):
            raise ValueError('Gemini is not configured in Veridex')
        return {'provider': 'gemini_api', 'model': config.model, 'reasoning': rule['reasoning']}
    return {**rule, 'reasoning': reasoning or rule['reasoning']}


def catalog(registry):
    default = select_model('conversation')
    choices = []
    for key, rule in manual_rules(registry).items():
        if rule['provider'] == 'gemini_api':
            config = load_gemini_config()
            available = gemini_enabled(config)
            choices.append({'id': key, 'label': f'Gemini · {config.model}' if available else 'Gemini · Not configured', 'available': available})
        else:
            choices.append({'id': key, 'label': rule['model'], 'available': True, 'reasoning_options': rule.get('reasoning_options', []), 'default_reasoning': rule['reasoning']})
    return {'default_model': default.model, 'choices': choices}


def codex_policy(task_type, selection):
    return ModelPolicy(task_type=task_type, model=selection['model'], reasoning_effort=selection['reasoning'])
