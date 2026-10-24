(() => {
    const imageMimeTypes = new Set(['image/jpeg', 'image/png', 'image/webp']);
    const zones = [...document.querySelectorAll('.file-upload-box, [data-maintenance-image-zone]')];
    let activeInput = null;

    function setFiles(input, files) {
        const transfer = new DataTransfer();
        [...files].forEach(file => transfer.items.add(file));
        input.files = transfer.files;
        input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function previewImage(input, zone, file) {
        if (!imageMimeTypes.has(file.type)) return;

        let preview = zone.querySelector('.maintenance-image-preview, .thumb-preview');
        if (!preview) {
            preview = document.createElement('img');
            preview.className = 'maintenance-image-pasted-preview';
            preview.alt = 'معاينة الصورة المرفقة';
            zone.appendChild(preview);
        }

        if (preview.dataset.objectUrl) {
            URL.revokeObjectURL(preview.dataset.objectUrl);
        }
        const objectUrl = URL.createObjectURL(file);
        preview.src = objectUrl;
        preview.dataset.objectUrl = objectUrl;
        preview.hidden = false;
        preview.style.display = 'block';

        const prompt = zone.querySelector('.maintenance-image-prompt');
        if (prompt) prompt.hidden = true;
    }

    function assignFiles(input, files, zone) {
        const selected = [...files].filter(file => {
            if (input.name === 'photo_before' || input.name === 'photo_after') {
                return imageMimeTypes.has(file.type);
            }
            return true;
        });
        if (!selected.length) return;
        setFiles(input, [selected[0]]);
        if (imageMimeTypes.has(selected[0].type)) {
            previewImage(input, zone, selected[0]);
        }
    }

    zones.forEach(zone => {
        const input = zone.querySelector('input[type="file"]');
        if (!input) return;

        zone.classList.add('maintenance-image-drop-zone');
        zone.tabIndex = 0;
        zone.setAttribute('role', 'button');
        zone.setAttribute('aria-label', 'أرفق صورة بالسحب والإفلات أو اللصق أو اختيار ملف');

        zone.addEventListener('pointerdown', () => {
            activeInput = input;
        });
        zone.addEventListener('focus', () => {
            activeInput = input;
        });
        zone.addEventListener('dragover', event => {
            event.preventDefault();
            zone.classList.add('is-dragging');
        });
        zone.addEventListener('dragleave', event => {
            if (!zone.contains(event.relatedTarget)) {
                zone.classList.remove('is-dragging');
            }
        });
        zone.addEventListener('drop', event => {
            event.preventDefault();
            event.stopPropagation();
            zone.classList.remove('is-dragging');
            assignFiles(input, event.dataTransfer.files, zone);
        });
        zone.addEventListener('keydown', event => {
            if ((event.key === 'Enter' || event.key === ' ') && !event.target.closest('button')) {
                event.preventDefault();
                input.click();
            }
        });
        input.addEventListener('change', () => {
            const file = input.files[0];
            if (file && imageMimeTypes.has(file.type)) {
                previewImage(input, zone, file);
            }
        });

        if (input.files.length && imageMimeTypes.has(input.files[0].type)) {
            previewImage(input, zone, input.files[0]);
        }
    });

    document.addEventListener('paste', event => {
        const imageFiles = [...(event.clipboardData?.items || [])]
            .filter(item => item.kind === 'file' && imageMimeTypes.has(item.type))
            .map(item => item.getAsFile())
            .filter(Boolean);
        if (!imageFiles.length) return;

        const focusedZone = document.activeElement?.closest(
            '.file-upload-box, [data-maintenance-image-zone]',
        );
        const focusedInput = focusedZone?.querySelector('input[type="file"]');
        const input = focusedInput || activeInput || document.querySelector(
            'input[name="photo_before"]',
        );
        const zone = input?.closest('.file-upload-box, [data-maintenance-image-zone]');
        if (!input || !zone) return;

        event.preventDefault();
        assignFiles(input, imageFiles, zone);
    });
})();
