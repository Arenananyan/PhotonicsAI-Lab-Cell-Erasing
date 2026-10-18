"""Factual read-only display if the language service cannot compose an answer."""
def measured_summary(facts):
    lines=['LLM պատասխանը հասանելի չէ։ Գործիքներից ստացված տվյալներ՝']
    lines.append('Պրինտեր՝ '+('սիմուլյացիա' if facts['simulated_printer'] else 'իրական'))
    position=facts.get('position',{})
    xyz=position.get('data',{}).get('data',{}).get('position_mm') if position.get('available') else None
    lines.append('Դիրք (մմ)՝ '+str(xyz) if xyz else 'Գլխիկի դիրքը հասանելի չէ։')
    printer=facts.get('printer',{})
    hooks=printer.get('data',{}).get('state',{}).get('webhooks',{})
    lines.append('Պրինտերի վիճակ՝ '+str(hooks.get('state_message') or hooks.get('state') or 'անհասանելի'))
    obs=facts.get('observation',{})
    if obs.get('available'):
        counts=obs['counts']
        lines.append(f"Կապույտ՝ {counts['blue']}, կանաչ՝ {counts['green']}, ընդհանուր՝ {sum(counts.values())}։")
        lines.append('Կադր՝ '+obs['frame_id']+' · '+obs['acquired_at'])
    else:
        lines.append('Բջիջների քանակն անհայտ է․ '+str(obs.get('error','Պատկերը հասանելի չէ։')))
    return '\n'.join(lines)
