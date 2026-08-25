/**
 * 登录/注册页面交互逻辑
 * - 表单切换
 * - 前端验证（密码强度、用户名格式）
 * - AJAX 调用 /api/auth/login 和 /api/auth/register
 * - 记住登录、隐私协议
 * - Toast 提示
 */
(function () {
    'use strict';

    var toastTimer = null;

    function showToast(msg, type) {
        var el = document.getElementById('toast');
        if (!el) return;
        el.textContent = msg;
        el.className = 'toast show' + (type === 'error' ? ' error' : '');
        if (toastTimer) clearTimeout(toastTimer);
        toastTimer = setTimeout(function () {
            el.className = 'toast';
        }, 2500);
    }

    function togglePassword(inputId, btn) {
        var input = document.getElementById(inputId);
        if (!input) return;
        if (input.type === 'password') {
            input.type = 'text';
        } else {
            input.type = 'password';
        }
    }

    function showRegister() {
        document.getElementById('login-form').classList.add('form-hidden');
        document.getElementById('register-form').classList.remove('form-hidden');
    }

    function showLogin() {
        document.getElementById('register-form').classList.add('form-hidden');
        document.getElementById('login-form').classList.remove('form-hidden');
    }

    function setLoading(btn, loading) {
        if (!btn) return;
        btn.disabled = loading;
        btn.textContent = loading ? '处理中...' : (btn.id === 'login-submit' ? '登录' : '注册');
    }

    function getRedirectUrl() {
        var params = new URLSearchParams(window.location.search);
        return params.get('next') || '/';
    }

    /**
     * 密码强度检测（前端实时显示）
     * 返回: 'weak' | 'medium' | 'strong' | ''
     */
    function evaluatePassword(pw) {
        if (!pw) return '';
        if (pw.length < 8) return 'weak';
        var hasLetter = /[a-zA-Z]/.test(pw);
        var hasDigit = /\d/.test(pw);
        if (!hasLetter || !hasDigit) return 'weak';
        var hasUpper = /[A-Z]/.test(pw);
        var hasLower = /[a-z]/.test(pw);
        var hasSpecial = /[!@#$%^&*()_+\-=\[\]{}|;:,.<>?~]/.test(pw);
        if (pw.length >= 12 && hasUpper && hasLower && hasDigit && hasSpecial) return 'strong';
        if (pw.length >= 10 && hasDigit && hasSpecial) return 'medium';
        return 'medium';
    }

    function checkPasswordStrength() {
        var pw = document.getElementById('reg-password').value;
        var bars = [
            document.getElementById('pw-bar-1'),
            document.getElementById('pw-bar-2'),
            document.getElementById('pw-bar-3')
        ];
        var label = document.getElementById('pw-label');
        var level = evaluatePassword(pw);

        // 重置
        bars.forEach(function (b) { b.className = 'pw-bar'; });
        label.className = 'pw-label';

        if (!pw) {
            label.textContent = '密码强度：未输入';
            return;
        }

        var text = { weak: '弱', medium: '中', strong: '强' };
        var count = { weak: 1, medium: 2, strong: 3 };
        var n = count[level] || 0;
        for (var i = 0; i < n; i++) {
            bars[i].classList.add(level);
        }
        label.classList.add(level);
        label.textContent = '密码强度：' + (text[level] || '未知');
    }

    function doLogin() {
        var username = document.getElementById('login-username').value.trim();
        var password = document.getElementById('login-password').value;
        var remember = document.getElementById('login-remember') ? document.getElementById('login-remember').checked : false;
        var btn = document.getElementById('login-submit');

        if (!username) { showToast('请输入用户名或邮箱', 'error'); return; }
        if (!password) { showToast('请输入密码', 'error'); return; }

        setLoading(btn, true);
        fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: username, password: password, remember_me: remember })
        })
        .then(function (resp) {
            return resp.json().then(function (data) {
                return { status: resp.status, data: data };
            });
        })
        .then(function (result) {
            setLoading(btn, false);
            if (result.status === 200 && result.data.status === 'success') {
                showToast('登录成功');
                setTimeout(function () {
                    window.location.href = getRedirectUrl();
                }, 500);
            } else if (result.status === 429) {
                showToast(result.data.error || '登录失败次数过多，请稍后重试', 'error');
            } else {
                showToast(result.data.error || '登录失败', 'error');
            }
        })
        .catch(function () {
            setLoading(btn, false);
            showToast('网络错误，请重试', 'error');
        });
    }

    function doRegister() {
        var username = document.getElementById('reg-username').value.trim();
        var email = document.getElementById('reg-email').value.trim();
        var password = document.getElementById('reg-password').value;
        var confirm = document.getElementById('reg-confirm').value;
        var agree = document.getElementById('reg-agree') ? document.getElementById('reg-agree').checked : false;
        var btn = document.getElementById('register-submit');

        if (!username) { showToast('请输入用户名', 'error'); return; }
        if (username.length < 3) { showToast('用户名至少 3 个字符', 'error'); return; }
        if (!agree) { showToast('请先阅读并同意隐私政策', 'error'); return; }

        // 密码强度校验
        var level = evaluatePassword(password);
        if (level === 'weak') {
            showToast('密码至少 8 位，必须包含字母和数字', 'error');
            return;
        }
        if (password !== confirm) { showToast('两次密码不一致', 'error'); return; }

        setLoading(btn, true);
        fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username: username,
                email: email,
                password: password,
                agree_privacy: true
            })
        })
        .then(function (resp) {
            return resp.json().then(function (data) {
                return { status: resp.status, data: data };
            });
        })
        .then(function (result) {
            setLoading(btn, false);
            if ((result.status === 200 || result.status === 201) && result.data.status === 'success') {
                showToast('注册成功，请登录');
                setTimeout(function () {
                    showLogin();
                    document.getElementById('login-username').value = username;
                    document.getElementById('login-password').focus();
                }, 800);
            } else {
                showToast(result.data.error || '注册失败', 'error');
            }
        })
        .catch(function () {
            setLoading(btn, false);
            showToast('网络错误，请重试', 'error');
        });
    }

    // 回车提交
    document.addEventListener('DOMContentLoaded', function () {
        var loginPw = document.getElementById('login-password');
        if (loginPw) {
            loginPw.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') doLogin();
            });
        }
        var loginUser = document.getElementById('login-username');
        if (loginUser) {
            loginUser.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') doLogin();
            });
        }
        var regConfirm = document.getElementById('reg-confirm');
        if (regConfirm) {
            regConfirm.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') doRegister();
            });
        }
    });

    // 暴露到全局供 onclick 使用
    window.togglePassword = togglePassword;
    window.showRegister = showRegister;
    window.showLogin = showLogin;
    window.doLogin = doLogin;
    window.doRegister = doRegister;
    window.showToast = showToast;
    window.checkPasswordStrength = checkPasswordStrength;
})();
