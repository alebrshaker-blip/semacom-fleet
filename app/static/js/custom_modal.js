// إنشاء عنصر النافذة تلقائياً في الصفحة
(function initModal() {
    const modalHTML = `
    <div id="customModalOverlay" class="custom-modal-overlay" role="presentation">
        <div class="custom-modal-card" role="dialog" aria-modal="true" aria-labelledby="modalTitle" aria-describedby="modalMessage">
            <div id="modalIcon" class="modal-icon warning">⚠️</div>
            <h3 id="modalTitle" class="modal-title">تأكيد الإجراء</h3>
            <p id="modalMessage" class="modal-message">هل أنت تأكد من الاستمرار؟</p>
            <div class="modal-actions">
                <button id="btnModalCancel" class="btn-modal btn-modal-cancel">إلغاء</button>
                <button id="btnModalConfirm" class="btn-modal btn-modal-confirm">تأكيد</button>
            </div>
        </div>
    </div>`;
    document.body.insertAdjacentHTML('beforeend', modalHTML);
})();

const customModalOverlay = document.getElementById('customModalOverlay');
customModalOverlay.addEventListener('click', (event) => {
    if (event.target === customModalOverlay && document.getElementById('btnModalCancel').style.display !== 'none') {
        document.getElementById('btnModalCancel').click();
    }
});

document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && customModalOverlay.classList.contains('active')) {
        const cancelButton = document.getElementById('btnModalCancel');
        if (cancelButton.style.display !== 'none') cancelButton.click();
        else document.getElementById('btnModalConfirm').click();
    }
});

// دالة نداء التنبيهات البسيطة (بديل alert)
function sysAlert(message, title = 'تنبيه', type = 'info') {
    return new Promise((resolve) => {
        const overlay = document.getElementById('customModalOverlay');
        const icon = document.getElementById('modalIcon');
        const titleEl = document.getElementById('modalTitle');
        const msgEl = document.getElementById('modalMessage');
        const btnCancel = document.getElementById('btnModalCancel');
        const btnConfirm = document.getElementById('btnModalConfirm');

        // ضبط الأيقونة والألوان
        icon.className = `modal-icon ${type}`;
        icon.innerText = type === 'success' ? '✓' : type === 'danger' ? '✕' : type === 'warning' ? '⚠️' : 'ℹ️';
        
        titleEl.innerText = title;
        msgEl.innerText = message;
        btnCancel.style.display = 'none'; // إخفاء زر الإلغاء للتنبيه العادي
        btnConfirm.className = 'btn-modal btn-modal-confirm';
        btnConfirm.innerText = 'موافق';

        overlay.classList.add('active');

        btnConfirm.onclick = () => {
            overlay.classList.remove('active');
            resolve(true);
        };
    });
}

// دالة نداء التأكيد (بديل confirm)
function sysConfirm(message, title = 'تأكيد العملية', type = 'warning', confirmText = 'نعم، استمر') {
    return new Promise((resolve) => {
        const overlay = document.getElementById('customModalOverlay');
        const icon = document.getElementById('modalIcon');
        const titleEl = document.getElementById('modalTitle');
        const msgEl = document.getElementById('modalMessage');
        const btnCancel = document.getElementById('btnModalCancel');
        const btnConfirm = document.getElementById('btnModalConfirm');

        icon.className = `modal-icon ${type}`;
        icon.innerText = type === 'danger' ? '🗑️' : '⚠️';
        
        titleEl.innerText = title;
        msgEl.innerText = message;
        btnCancel.style.display = 'block';
        btnConfirm.innerText = confirmText;
        btnConfirm.className = `btn-modal ${type === 'danger' ? 'btn-modal-danger' : 'btn-modal-confirm'}`;

        overlay.classList.add('active');

        btnConfirm.onclick = () => {
            overlay.classList.remove('active');
            resolve(true);
        };

        btnCancel.onclick = () => {
            overlay.classList.remove('active');
            resolve(false);
        };
    });
}
// استبدال دالة alert الأصلية للمتصفح بالنافذة المخصصة تلقائياً
window.alert = function(message, title = 'تنبيه') {
    sysAlert(message, title, 'info');
};

document.addEventListener('click', async (event) => {
    const logoutLink = event.target.closest('[data-confirm-logout]');
    if (logoutLink) {
        event.preventDefault();
        const confirmed = await sysConfirm('هل ترغب في تسجيل الخروج من النظام؟', 'تأكيد تسجيل الخروج', 'warning', 'تسجيل الخروج');
        if (confirmed) window.location.assign(logoutLink.href);
        return;
    }

    const deleteButton = event.target.closest('[data-confirm-delete]');
    if (deleteButton) {
        const targetName = deleteButton.dataset.targetName || 'السجل المحدد';
        const confirmed = await sysConfirm(
            `هل تريد حذف ${targetName}؟ لا يمكن التراجع عن هذا الإجراء.`,
            'تأكيد الحذف',
            'danger',
            'نعم، احذف'
        );
        if (confirmed) window.location.assign(deleteButton.dataset.confirmDelete);
    }
});