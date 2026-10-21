(() => {
    const fields = [...document.querySelectorAll('[data-unique-check]')];
    if (!fields.length) return;

    const pending = new WeakMap();
    const debounceTimers = new WeakMap();
    const form = fields[0].form;

    function showFeedback(input, message) {
        const feedback = document.getElementById(input.dataset.uniqueFeedback);
        if (feedback) {
            feedback.textContent = message;
            feedback.hidden = !message;
        }
    }

    async function checkField(input) {
        const timer = debounceTimers.get(input);
        if (timer) {
            window.clearTimeout(timer);
            debounceTimers.delete(input);
        }
        const value = input.value.trim();
        if (!value) {
            pending.set(input, Symbol());
            input.dataset.uniqueDuplicate = 'false';
            showFeedback(input, '');
            input.classList.remove('unique-invalid');
            return false;
        }

        const requestToken = Symbol();
        pending.set(input, requestToken);
        const query = new URLSearchParams({
            field: input.dataset.uniqueField,
            value,
        });
        try {
            const response = await fetch(`${input.dataset.uniqueCheck}?${query}`, {
                credentials: 'same-origin',
                headers: { Accept: 'application/json' },
            });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(`Unique check failed with status ${response.status}.`);
            }
            if (typeof result.duplicate !== 'boolean' || typeof result.message !== 'string') {
                throw new Error('Unique check returned an invalid response.');
            }
            if (pending.get(input) !== requestToken) return null;

            const duplicate = result.duplicate;
            input.dataset.uniqueDuplicate = String(duplicate);
            input.classList.toggle('unique-invalid', duplicate);
            showFeedback(input, duplicate ? result.message : '');
            return duplicate;
        } catch (error) {
            if (pending.get(input) !== requestToken) return null;
            console.error('Unable to verify whether this value is unique.', error);
            input.dataset.uniqueDuplicate = 'unknown';
            input.classList.add('unique-invalid');
            showFeedback(input, 'تعذر التحقق من القيمة الآن. يرجى المحاولة مرة أخرى.');
            return null;
        }
    }

    fields.forEach(input => {
        input.addEventListener('input', () => {
            const timer = debounceTimers.get(input);
            if (timer) window.clearTimeout(timer);
            pending.set(input, Symbol());
            input.dataset.uniqueDuplicate = 'unknown';
            input.classList.remove('unique-invalid');
            showFeedback(input, '');
            debounceTimers.set(input, window.setTimeout(() => {
                debounceTimers.delete(input);
                checkField(input);
            }, 250));
        });
        input.addEventListener('blur', () => checkField(input));
    });

    if (form) {
        form.addEventListener('submit', async event => {
            if (form.dataset.uniqueCheckPassed === 'true') {
                delete form.dataset.uniqueCheckPassed;
                return;
            }
            event.preventDefault();
            const checks = await Promise.all(fields.map(checkField));
            if (checks.some(result => result === null)) {
                fields.find(input => input.dataset.uniqueDuplicate === 'unknown')?.focus();
                return;
            }
            if (checks.some(Boolean)) {
                fields.find(input => input.dataset.uniqueDuplicate === 'true')?.focus();
                return;
            }
            form.dataset.uniqueCheckPassed = 'true';
            if (event.submitter) form.requestSubmit(event.submitter);
            else form.requestSubmit();
        });
    }
})();
