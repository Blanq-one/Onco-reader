// The decision panel at the top of Results and Summary: the suggested next step, why, who reviews it,
// and a form to record the decision (it goes into review.json, never into audit.json).
import { h, toast } from './util.js';
import { ROLES, REVIEW_ROLES, getRole } from './state.js';
import { STEPS, STEP_ORDER, analyse, keyLimitations, savedStep, recordStep } from './decision.js';
import { interpTag } from './ui.js';

const claimLink = (id, from) => h('a', { class: 'cid', href: '#/claim/' + encodeURIComponent(id) + '?from=' + from }, id);
const when = (iso) => { try { return new Date(iso).toLocaleString(); } catch (e) { return iso; } };

export function decisionPanel(where) {
  const a = analyse();
  const s = STEPS[a.step];
  const sec = h('section', { class: 'card decision-panel step-' + a.step, 'aria-labelledby': 'dp-h-' + where, id: 'decision' });
  sec.append(
    h('div', { class: 'dp-kicker' }, h('span', {}, 'Suggested next step'), interpTag()),
    h('h2', { id: 'dp-h-' + where, class: 'dp-step' }, h('span', { class: 'dp-ic', 'aria-hidden': 'true' }, s.icon), s.label),
    h('p', { class: 'dp-why' }, s.text + (a.groups.overridden.length ? ' This counts the verdicts as changed by reviewers.' : '')));

  sec.append(h('div', { class: 'dp-cols' },
    h('div', {}, h('h3', { class: 'dp-sub' }, 'Why'),
      h('ul', { class: 'dp-reasons' }, a.reasons.map((r) => h('li', {},
        h('span', {}, r.text + ': '), h('span', { class: 'dp-ids' }, r.ids.map((id, i) => [i ? ', ' : '', claimLink(id, where)])))))),
    h('div', {}, h('h3', { class: 'dp-sub' }, 'Who needs to review it'),
      h('ul', { class: 'dp-who' }, a.reviewers.map((r) => h('li', {}, h('b', {}, ROLES[r.role].label), ': ' + r.why))))));

  const lims = keyLimitations();
  sec.append(h('details', { class: 'dp-lims' }, h('summary', {}, 'Key limitations (' + lims.length + ')'),
    h('ul', {}, lims.map((l) => h('li', {}, l.text, ' ', h('span', { class: 'muted' }, '(', l.finding_ids.map((id, i) => [i ? ', ' : '', claimLink(id, where)]), ')'))))));

  sec.append(decisionForm(a, where));
  return sec;
}

function decisionForm(a, where) {
  const saved = savedStep();
  const name = 'dp-step-' + where;
  const startStep = saved ? saved.step : a.step;
  const radios = STEP_ORDER.map((k) => h('label', { class: 'dp-opt' + (k === a.step ? ' suggested' : '') },
    h('input', { type: 'radio', name, value: k, checked: k === startStep }),
    h('span', {}, STEPS[k].label), k === a.step ? h('span', { class: 'chip' }, 'suggested') : null));
  const reasonId = 'dp-reason-' + where, roleId = 'dp-role-' + where, errId = 'dp-err-' + where;
  const reason = h('input', { type: 'text', id: reasonId, maxlength: '200', autocomplete: 'off', 'aria-describedby': reasonId + '-hint' });
  reason.value = saved && saved.reason ? saved.reason : '';
  const reasonBox = h('div', { class: 'dp-reason' },
    h('label', { for: reasonId }, 'Why a different step? (required, one line)'), reason,
    h('p', { id: reasonId + '-hint', class: 'muted dp-hint' }, 'You chose a step other than the suggested one, so say why. It is saved in review.json.'));
  const roleNow = saved ? saved.role : getRole();
  const role = h('select', { id: roleId, required: true },
    h('option', { value: '' }, 'Choose your role'),
    REVIEW_ROLES.map((r) => h('option', Object.assign({ value: r }, r === roleNow ? { selected: true } : {}), ROLES[r].label)));
  const err = h('p', { id: errId, class: 'dp-err', role: 'alert' });
  const status = h('p', { class: 'dp-status', role: 'status' });
  const chosen = () => (sec.querySelector('input[name="' + name + '"]:checked') || {}).value;
  const syncReason = () => { reasonBox.hidden = chosen() === a.step; };
  const showStatus = (rec) => {
    if (!rec) { status.textContent = 'No decision recorded yet.'; status.classList.remove('ok'); return; }
    status.classList.add('ok');
    status.textContent = 'Recorded: ' + STEPS[rec.step].label + ', by the ' + ROLES[rec.role].name + ', ' + when(rec.at) + '.'
      + (rec.step !== rec.suggested ? ' Reason: ' + rec.reason : '')
      + (rec.suggested !== a.step ? ' The suggestion has changed since then; record again if your decision changes.' : '')
      + ' It is saved in review.json.';
  };
  const fail = (msg, field) => {
    err.textContent = msg;
    field.setAttribute('aria-invalid', 'true'); field.setAttribute('aria-errormessage', errId); field.focus();
  };
  const submit = h('button', { class: 'btn primary', type: 'submit' }, 'Record the decision');
  const sec = h('form', { class: 'dp-form no-print', novalidate: true, 'aria-label': 'Record the next step' },
    h('fieldset', { class: 'dp-steps' }, h('legend', {}, 'Your decision'), h('div', { class: 'dp-opts' }, radios)),
    reasonBox,
    h('div', { class: 'dp-role' }, h('label', { for: roleId }, 'Your role'), role),
    h('div', { class: 'row' }, submit), err, status);
  sec.addEventListener('change', (e) => {
    if (e.target.name === name) syncReason();
    if (e.target === role) role.removeAttribute('aria-invalid');
  });
  reason.addEventListener('input', () => reason.removeAttribute('aria-invalid'));
  sec.addEventListener('submit', (e) => {
    e.preventDefault();
    err.textContent = '';
    const step = chosen();
    const why = reason.value.trim().replace(/\s+/g, ' ');
    if (!role.value) return fail('Choose your role before recording the decision.', role);
    if (step !== a.step && why.length < 3) return fail('Say in one line why you chose ' + STEPS[step].label + ' instead of ' + STEPS[a.step].label + '.', reason);
    const rec = recordStep(step, step !== a.step ? why : null, role.value);
    showStatus(rec);
    toast('Decision recorded: ' + STEPS[step].label);
  });
  syncReason();
  showStatus(saved);
  return sec;
}
