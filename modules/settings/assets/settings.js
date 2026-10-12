function switchTab(evt, tabId) {
    evt.preventDefault();

    // 1. إخفاء جميع التبويبات
    const tabPanes = document.querySelectorAll('.tab-pane');
    tabPanes.forEach(pane => pane.classList.remove('active'));

    // 2. إلغاء النشاط عن جميع الأزرار
    const navTabs = document.querySelectorAll('.nav-tab');
    navTabs.forEach(tab => tab.classList.remove('active'));

    // 3. تفعيل التبويب المختار
    const targetPane = document.getElementById(tabId);
    if (targetPane) {
        targetPane.classList.add('active');
    }

    // 4. تفعيل زر التبويب الحالي
    evt.currentTarget.classList.add('active');
}

function saveAllSettings() {
    const form = document.getElementById('settingsForm');
    const formData = new FormData(form);
    const data = Object.fromEntries(formData.entries());

    fetch('/settings/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
    .then(res => res.json())
    .then(res => {
        alert(res.message || 'تم حفظ الإعدادات بنجاح');
    })
    .catch(err => {
        alert('حدث خطأ أثناء الحفظ');
    });
}

function saveAccountSettings(e) {
    e.preventDefault();
    const form = document.getElementById('accountForm');
    const formData = new FormData(form);
    const data = Object.fromEntries(formData.entries());

    fetch('/settings/account/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
    .then(res => res.json())
    .then(res => {
        alert(res.message);
    })
    .catch(err => {
        alert('حدث خطأ أثناء التحديث');
    });
}