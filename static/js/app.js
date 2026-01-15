class CryptoPayApp {
    constructor() {
        this.user = null;
        this.balanceSol = 0;
        this.balanceRub = 0;
        this.walletAddress = null;
        this.currentPayment = null;
        this.telegramWebApp = null;
        this.qrScanner = null;
        this.paymentCheckInterval = null;
        this.init();
    }

    init() {
        this.initTelegramWebApp();
        this.initServiceWorker();
        this.loadWelcomeText();
        this.checkAuth();
        this.setupEventListeners();
        this.initQRScanner();
    }

    initTelegramWebApp() {
        if (window.Telegram && Telegram.WebApp) {
            this.telegramWebApp = Telegram.WebApp;
            this.telegramWebApp.expand();
            this.telegramWebApp.enableClosingConfirmation();
            
            this.telegramWebApp.setHeaderColor('#6366f1');
            this.telegramWebApp.setBackgroundColor('#0f172a');
        }
    }

    async initServiceWorker() {
        if ('serviceWorker' in navigator) {
            try {
                await navigator.serviceWorker.register('/static/sw.js');
                console.log('Service Worker registered');
            } catch (error) {
                console.log('Service Worker registration failed:', error);
            }
        }
    }

    initQRScanner() {
        this.qrScanner = new QRScanner();
    }

    async checkAuth() {
        try {
            const response = await fetch('/api/user/info');
            if (response.ok) {
                const userData = await response.json();
                this.user = userData;
                this.balanceSol = userData.balance_sol || 0;
                this.balanceRub = userData.balance_rub || 0;
                this.walletAddress = userData.wallet_address;
                this.showUserInterface();
                this.loadTransactions();
            } else {
                this.showAuthInterface();
            }
        } catch (error) {
            this.showAuthInterface();
        }
    }

    showAuthInterface() {
        document.getElementById('authButtons').classList.remove('hidden');
        document.getElementById('userInfo').classList.add('hidden');
        document.getElementById('balanceCard').classList.add('hidden');
        document.getElementById('transactionsCard').classList.add('hidden');
    }

    showUserInterface() {
        document.getElementById('authButtons').classList.add('hidden');
        document.getElementById('userInfo').classList.remove('hidden');
        document.getElementById('balanceCard').classList.remove('hidden');
        document.getElementById('transactionsCard').classList.remove('hidden');
        
        const username = this.user?.username || this.user?.first_name || 'Пользователь';
        document.getElementById('username').textContent = username;
        
        this.updateBalanceDisplay();
        
        const testWarning = document.getElementById('testBalanceWarning');
        if (this.user?.is_test_balance) {
            if (!testWarning) {
                const warning = document.createElement('div');
                warning.id = 'testBalanceWarning';
                warning.className = 'test-warning';
                warning.innerHTML = `
                    <div class="warning-content">
                        <i class="fas fa-exclamation-triangle"></i>
                        <span>Внимание: на балансе имеется тестовая валюта из Devnet. Средства не имеют реальной стоимости.</span>
                    </div>
                `;
                document.querySelector('.main-content').prepend(warning);
            }
        } else if (testWarning) {
            testWarning.remove();
        }
    }

    updateBalanceDisplay() {
        const totalBalance = document.getElementById('totalBalance');
        const solBalance = document.getElementById('solBalance');
        
        const isTestBalance = this.user?.is_test_balance || false;
        const testBadge = isTestBalance ? '<span class="test-badge">ТЕСТ</span>' : '';
        
        totalBalance.innerHTML = `${Math.round(this.balanceRub)} ₽ ${testBadge}`;
        solBalance.textContent = `${this.balanceSol.toFixed(6)} SOL`;
        
        if (isTestBalance) {
            totalBalance.classList.add('test-balance');
        } else {
            totalBalance.classList.remove('test-balance');
        }
    }

    async loadWelcomeText() {
        try {
            const response = await fetch('/api/home/text');
            const data = await response.json();
            document.getElementById('welcomeContent').textContent = data.text || 'Добро пожаловать в CryptoPay!';
        } catch (error) {
            document.getElementById('welcomeContent').textContent = 
                'Добро пожаловать в CryptoPay! Пополняйте баланс Solana и оплачивайте покупки по QR-коду.';
        }
    }

    async loadTransactions() {
        try {
            const response = await fetch('/api/user/transactions');
            if (response.ok) {
                const data = await response.json();
                console.log('Loaded transactions:', data.transactions);
                this.renderTransactions(data.transactions || []);
            } else {
                console.error('Error loading transactions:', response.status);
                this.renderTransactions([]);
            }
        } catch (error) {
            console.error('Error loading transactions:', error);
            this.renderTransactions([]);
        }
    }

    renderTransactions(transactions) {
        const container = document.getElementById('transactionsList');
        container.innerHTML = '';

        if (!transactions || transactions.length === 0) {
            container.innerHTML = '<p class="no-transactions">Нет операций</p>';
            return;
        }

        transactions.forEach(transaction => {
            const item = document.createElement('div');
            const transactionType = transaction.transaction_type || transaction.type || 'payment';
            item.className = `transaction-item ${transactionType === 'test_deposit' ? 'test-transaction' : ''}`;
            
            const amount = transaction.amount ? 
                `${transaction.amount > 0 ? '+' : ''}${Number(transaction.amount).toFixed(6)} ${transaction.currency || 'SOL'}` :
                '0.000000 SOL';
            
            const rubAmount = transaction.amount_rub ?
                `${transaction.amount_rub > 0 ? '+' : ''}${Math.round(transaction.amount_rub)} ₽` : '0 ₽';
            
            const displayType = this.getTransactionType(transactionType);
            const statusText = this.getStatusText(transaction.status || 'pending');
            
            let date = "Дата не определена";
            if (transaction.created_at) {
                try {
                    let dateObj = new Date(transaction.created_at);
                    
                    if (isNaN(dateObj.getTime())) {
                        const dateStr = transaction.created_at.toString();
                        
                        const parts = dateStr.match(/(\d{2})\.(\d{2})\.(\d{4}) (\d{2}):(\d{2}):(\d{2})/);
                        if (parts) {
                            dateObj = new Date(`${parts[3]}-${parts[2]}-${parts[1]}T${parts[4]}:${parts[5]}:${parts[6]}`);
                        } else {
                            dateObj = new Date(dateStr.replace(' ', 'T'));
                        }
                    }
                    
                    if (isNaN(dateObj.getTime())) {
                        dateObj = new Date();
                    }
                    
                    dateObj.setHours(dateObj.getHours() + 3);
                    
                    date = dateObj.toLocaleString('ru-RU', {
                        day: '2-digit',
                        month: '2-digit', 
                        year: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit'
                    });
                    
                } catch (e) {
                    console.error('Error parsing date:', e, transaction.created_at);
                    date = new Date().toLocaleString('ru-RU');
                }
            } else {
                date = new Date().toLocaleString('ru-RU');
            }
            
            const testBadge = transactionType === 'test_deposit' ? 
                '<span class="test-badge" style="margin-left: 5px;">ТЕСТ</span>' : '';
            
            item.innerHTML = `
                <div class="transaction-header">
                    <div>
                        <div class="transaction-type">${displayType} • ${transaction.currency || 'SOL'} ${testBadge}</div>
                        <div class="transaction-amount">${amount}</div>
                        <div class="transaction-rub-amount">${rubAmount}</div>
                    </div>
                    <div class="transaction-status ${transaction.status || 'pending'}">
                        ${statusText}
                    </div>
                </div>
                <div class="transaction-date">
                    ${date}
                </div>
            `;
            
            container.appendChild(item);
        });
    }

    getTransactionType(type) {
        const types = {
            'deposit': 'Пополнение',
            'payment': 'Оплата',
            'withdrawal': 'Вывод',
            'penalty': 'Штраф',
            'test_deposit': 'Тестовое пополнение'
        };
        return types[type] || type;
    }

    getStatusText(status) {
        const statuses = {
            'completed': '<i class="fas fa-check status-icon-completed"></i> Выполнено',
            'pending': '<i class="fas fa-clock status-icon-pending"></i> В обработке',
            'error': '<i class="fas fa-times status-icon-error"></i> Ошибка',
            'cancelled': '<i class="fas fa-ban status-icon-cancelled"></i> Отменено',
            'rejected': '<i class="fas fa-ban status-icon-cancelled"></i> Отменено',
            'in_progress': '<i class="fas fa-hourglass-half status-icon-pending"></i> В обработке',
            'waiting_user_confirmation': '<i class="fas fa-user-clock status-icon-pending"></i> Ожидание<br>подтверждения'
        };
        return statuses[status] || '<i class="fas fa-clock status-icon-pending"></i> В обработке';
    }

    setupEventListeners() {
        document.querySelectorAll('.nav-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const btnText = e.currentTarget.textContent || e.currentTarget.innerText;
                let section = 'main';
                
                if (btnText.includes('Главная')) {
                    section = 'main';
                } else if (btnText.includes('История')) {
                    section = 'history';
                } else if (btnText.includes('Сканировать')) {
                    section = 'scan';
                }
                
                console.log('Nav button clicked:', btnText, 'Section:', section);
                this.showSection(section);
            });
        });
        
        document.addEventListener('visibilitychange', function() {
            if (document.hidden && app && app.qrScanner) {
                app.qrScanner.stop();
            }
        });

        window.addEventListener('beforeunload', function() {
            if (app && app.qrScanner) {
                app.qrScanner.stop();
            }
        });
    }


    showSection(section) {
        console.log('Showing section:', section);
        
        const oldSections = document.querySelectorAll('.dynamic-section');
        oldSections.forEach(section => section.remove());
        
        document.querySelectorAll('.main-content > .glass-card').forEach(el => {
            el.classList.add('hidden');
        });
        
        switch(section) {
            case 'main':
                console.log('Showing main section');
                document.getElementById('balanceCard').classList.remove('hidden');
                document.getElementById('welcomeCard').classList.remove('hidden');
                document.getElementById('transactionsCard').classList.remove('hidden');
                break;
                
            case 'history':
                console.log('Showing history section');
                document.getElementById('transactionsCard').classList.remove('hidden');
                break;
                
            case 'scan':
                console.log('Showing scan section');
                this.showScanInterface();
                break;
        }
        
        this.updateActiveNavButton(section);
    }

    updateActiveNavButton(activeSection) {
        const navButtons = document.querySelectorAll('.nav-btn');
        navButtons.forEach(btn => {
            btn.classList.remove('active');
            
            const btnText = btn.textContent || btn.innerText;
            if (activeSection === 'main' && btnText.includes('Главная')) {
                btn.classList.add('active');
            } else if (activeSection === 'history' && btnText.includes('История')) {
                btn.classList.add('active');
            } else if (activeSection === 'scan' && btnText.includes('Сканировать')) {
                btn.classList.add('active');
            }
        });
    }

    showScanInterface() {
        console.log('Initializing scan interface');
        
        if (this.qrScanner && this.qrScanner.isScanning) {
            this.qrScanner.stop();
        }
        
        const oldSections = document.querySelectorAll('.dynamic-section');
        oldSections.forEach(section => section.remove());
        
        const scanHTML = `
            <div class="glass-card dynamic-section scan-section">
                <h3>Сканирование QR-кода</h3>
                <div class="scan-options">
                    <button class="btn btn-primary" onclick="startCameraScan()">
                        <i class="fas fa-camera"></i>
                        Камера
                    </button>
                    <input type="file" id="qrFileInput" accept="image/*" class="file-input" style="display:none;">
                    <button class="btn btn-secondary" onclick="document.getElementById('qrFileInput').click()">
                        <i class="fas fa-upload"></i>
                        Загрузить
                    </button>
                </div>
                <div id="cameraScanner" class="hidden">
                    <div class="qr-scanner-container">
                        <video id="qrScannerVideo" autoplay playsinline muted class="qr-scanner-video"></video>
                        <canvas id="qrScannerCanvas" style="display:none;"></canvas>
                        <div class="qr-scanner-overlay">
                            <div class="qr-scanner-frame">
                                <div class="qr-scanner-corner top-left"></div>
                                <div class="qr-scanner-corner top-right"></div>
                                <div class="qr-scanner-corner bottom-left"></div>
                                <div class="qr-scanner-corner bottom-right"></div>
                            </div>
                            <div class="qr-scanner-hint">Наведите камеру на QR-код</div>
                        </div>
                    </div>
                    <button class="btn btn-secondary btn-stop-scan" onclick="stopCameraScan()">
                        <i class="fas fa-stop"></i> Остановить сканирование
                    </button>
                </div>
                <div class="scan-tips">
                    <h4>Советы для лучшего сканирования:</h4>
                    <ul>
                        <li>Обеспечьте хорошее освещение</li>
                        <li>Держите камеру прямо напротив QR-кода</li>
                        <li>Убедитесь, что QR-код полностью в рамке</li>
                        <li>Избегайте бликов и отражений</li>
                    </ul>
                </div>
            </div>
        `;
        
        const container = document.createElement('div');
        container.innerHTML = scanHTML;
        document.querySelector('.main-content').appendChild(container.firstElementChild);

        document.getElementById('qrFileInput').addEventListener('change', function(event) {
            if (event.target.files && event.target.files[0]) {
                processQRFile(event.target.files[0]);
            }
        });
        
        console.log('Scan interface initialized');
    }

    startPaymentStatusCheck(transactionId) {
        if (this.paymentCheckInterval) {
            clearInterval(this.paymentCheckInterval);
        }

        let timeLeft = 180;
        this.updatePaymentTimer(timeLeft);

        this.paymentCheckInterval = setInterval(async () => {
            timeLeft--;
            this.updatePaymentTimer(timeLeft);

            if (timeLeft <= 0) {
                clearInterval(this.paymentCheckInterval);
                this.showPaymentResult('timeout', 'Время ожидания истекло');
                return;
            }

            try {
                const response = await fetch(`/api/payment/status/${transactionId}`);
                if (response.ok) {
                    const data = await response.json();
                    
                    if (data.status === 'completed') {
                        clearInterval(this.paymentCheckInterval);
                        this.showPaymentResult('success', 'Платеж успешно выполнен!');
                        this.checkAuth();
                        this.loadTransactions();
                    } else if (data.status === 'error' || data.status === 'cancelled') {
                        clearInterval(this.paymentCheckInterval);
                        this.showPaymentResult('error', data.error_message || 'Платеж отменен');
                        this.checkAuth();
                        this.loadTransactions();
                    }
                }
            } catch (error) {
                console.error('Error checking payment status:', error);
            }
        }, 1000);
    }

    updatePaymentTimer(seconds) {
        const timerElement = document.getElementById('paymentTimer');
        if (timerElement) {
            const minutes = Math.floor(seconds / 60);
            const secs = seconds % 60;
            timerElement.textContent = `${minutes}:${secs.toString().padStart(2, '0')}`;
        }
    }

    showPaymentResult(type, message) {
        const content = document.getElementById('paymentStatusContent');
        if (!content) return;

        const icons = {
            success: '<div class="status-icon-success"><i class="fas fa-check-circle"></i></div>',
            error: '<div class="status-icon-error"><i class="fas fa-times-circle"></i></div>',
            timeout: '<div class="status-icon-timeout"><i class="fas fa-clock"></i></div>'
        };

        content.innerHTML = `
            ${icons[type] || ''}
            <div class="status-message">${message}</div>
            <button class="btn btn-primary btn-close-status" onclick="hidePaymentStatus()">
                Закрыть
            </button>
        `;
    }
}

class QRScanner {
    constructor() {
        this.stream = null;
        this.isScanning = false;
        this.video = null;
        this.canvas = null;
        this.context = null;
        this.scanInterval = null;
        this.lastScanTime = 0;
        this.scanCooldown = 1000;
    }

    async start() {
        try {
            console.log('Запуск камеры...');
            
            if (this.isScanning) {
                console.log('Сканирование уже запущено');
                return true;
            }
            
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                throw new Error('Ваш браузер не поддерживает доступ к камере. Используйте HTTPS.');
            }

            const constraints = {
                video: {
                    width: { ideal: 1280, min: 640 },
                    height: { ideal: 720, min: 480 },
                    facingMode: 'environment',
                    frameRate: { ideal: 30, min: 15 }
                },
                audio: false
            };

            this.stream = await navigator.mediaDevices.getUserMedia(constraints);
            
            this.video = document.getElementById('qrScannerVideo');
            this.canvas = document.getElementById('qrScannerCanvas');
            
            if (!this.video || !this.canvas) {
                throw new Error('Элементы сканера не найдены');
            }
            
            this.context = this.canvas.getContext('2d', { willReadFrequently: true });
            this.video.srcObject = this.stream;
            
            await new Promise((resolve, reject) => {
                this.video.onloadedmetadata = () => {
                    this.video.play().then(resolve).catch(reject);
                };
                this.video.onerror = reject;
                
                setTimeout(() => reject(new Error('Таймаут загрузки видео')), 5000);
            });
            
            this.isScanning = true;
            this.scanInterval = setInterval(() => this.scanFrame(), 300);
            
            const scannerElement = document.getElementById('cameraScanner');
            if (scannerElement) {
                scannerElement.classList.remove('hidden');
            }
            
            console.log('Камера успешно запущена');
            return true;
            
        } catch (error) {
            console.error('Ошибка доступа к камере:', error);
            this.stop();
            
            let errorMessage = 'Не удалось получить доступ к камере: ';
            
            if (error.name === 'NotAllowedError') {
                errorMessage += 'Разрешите доступ к камере в настройках браузера';
            } else if (error.name === 'NotFoundError') {
                errorMessage += 'Камера не найдена';
            } else if (error.name === 'NotSupportedError') {
                errorMessage += 'Ваш браузер не поддерживает камеру';
            } else if (error.message.includes('HTTPS')) {
                errorMessage = 'Для работы камеры требуется HTTPS соединение. Запустите сервер с SSL.';
            } else {
                errorMessage += error.message;
            }
            
            showError(errorMessage);
            return false;
        }
    }

    stop() {
        console.log('Остановка сканирования...');
        this.isScanning = false;
        
        if (this.scanInterval) {
            clearInterval(this.scanInterval);
            this.scanInterval = null;
        }
        
        if (this.stream) {
            this.stream.getTracks().forEach(track => {
                track.stop();
            });
            this.stream = null;
        }
        
        if (this.video) {
            this.video.srcObject = null;
        }
        
        const scannerElement = document.getElementById('cameraScanner');
        if (scannerElement) {
            scannerElement.classList.add('hidden');
        }
        
        console.log('Сканирование остановлено');
    }

    scanFrame() {
        if (!this.isScanning || !this.video || this.video.readyState !== this.video.HAVE_ENOUGH_DATA) {
            return;
        }
        
        const now = Date.now();
        if (now - this.lastScanTime < this.scanCooldown) {
            return;
        }
        
        try {
            const videoWidth = this.video.videoWidth;
            const videoHeight = this.video.videoHeight;
            
            if (videoWidth === 0 || videoHeight === 0) return;
            
            this.canvas.width = videoWidth;
            this.canvas.height = videoHeight;
            
            this.context.drawImage(this.video, 0, 0, videoWidth, videoHeight);
            
            const imageData = this.context.getImageData(0, 0, videoWidth, videoHeight);
            
            const code = jsQR(imageData.data, imageData.width, imageData.height, {
                inversionAttempts: 'attemptBoth',
                canOverwriteImage: false
            });
            
            if (code) {
                console.log('QR-код распознан:', code.data);
                this.lastScanTime = now;
                this.stop();
                this.processQRCode(code.data);
                
                this.showScanSuccess();
            }
        } catch (error) {
            console.error('Ошибка сканирования кадра:', error);
        }
    }

    showScanSuccess() {
        const frame = document.querySelector('.qr-scanner-frame');
        if (frame) {
            frame.style.borderColor = '#10b981';
            setTimeout(() => {
                frame.style.borderColor = '#6366f1';
            }, 1000);
        }
    }

    async processQRCode(qrData) {
        try {
            showLoading('Обработка QR-кода...');
            
            const response = await fetch('/api/payment/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    qr_code_data: qrData
                })
            });
            
            const data = await response.json();
            hideLoading();
            
            if (data.success) {
                app.currentPayment = data;
                showPaymentModal(data);
                showSuccess('QR-код успешно распознан!');
            } else {
                showError(`Ошибка: ${data.error || 'Неизвестная ошибка'}`);
                setTimeout(() => this.start(), 2000);
            }
        } catch (error) {
            hideLoading();
            showError('Ошибка подключения к серверу');
            setTimeout(() => this.start(), 2000);
        }
    }
}

let app = new CryptoPayApp();

function showLoading(message = 'Загрузка...') {
    let loading = document.getElementById('loadingOverlay');
    if (!loading) {
        loading = document.createElement('div');
        loading.id = 'loadingOverlay';
        loading.className = 'modal';
        loading.innerHTML = `
            <div class="modal-content glass-card text-center">
                <div class="loading-spinner"></div>
                <div class="loading-message">${message}</div>
            </div>
        `;
        document.body.appendChild(loading);
    }
    loading.classList.remove('hidden');
}

function hideLoading() {
    const loading = document.getElementById('loadingOverlay');
    if (loading) {
        loading.classList.add('hidden');
    }
}

function showError(message) {
    const toast = document.createElement('div');
    toast.className = 'error-toast';
    toast.textContent = message;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.remove();
    }, 5000);
}

function showSuccess(message) {
    const toast = document.createElement('div');
    toast.className = 'success-toast';
    toast.textContent = message;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.remove();
    }, 4000);
}

async function showAuthModal(type) {
    const modal = document.getElementById('authModal');
    const title = document.getElementById('authModalTitle');
    const content = document.getElementById('authModalContent');
    
    title.textContent = type === 'register' ? 'Регистрация' : 'Вход';
    
    try {
        const response = await fetch('/api/auth/generate-session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type })
        });
        
        const data = await response.json();
        
        if (data.success) {
            content.innerHTML = `
                <p>Для ${type === 'register' ? 'регистрации' : 'входа'}:</p>
                <ol class="auth-steps">
                    <li>Нажмите на ссылку ниже</li>
                    <li>В боте нажмите START</li>
                    <li>Введите код с сайта в боте</li>
                    <li>Вернитесь на сайт</li>
                </ol>
                <div class="auth-bot-link">
                    <a href="${data.bot_url}" class="btn btn-primary" target="_blank">
                        <i class="fab fa-telegram"></i> Перейти в бота
                    </a>
                </div>
                <div class="auth-code-section">
                    <p>Или введите код из бота:</p>
                    <input type="text" id="authCodeInput" placeholder="6-значный код" maxlength="6" class="auth-code-input">
                    <button class="btn btn-primary btn-confirm-auth" onclick="submitAuthCode('${type}')">
                        <i class="fas fa-check"></i> Подтвердить
                    </button>
                </div>
            `;
        } else {
            content.innerHTML = `<p class="auth-error">Ошибка: ${data.error || 'Неизвестная ошибка'}</p>`;
        }
    } catch (error) {
        content.innerHTML = `<p class="auth-error">Ошибка подключения</p>`;
    }
    
    modal.classList.remove('hidden');
}

function hideAuthModal() {
    document.getElementById('authModal').classList.add('hidden');
}

async function submitAuthCode(type) {
    const code = document.getElementById('authCodeInput').value.trim();
    
    if (code.length !== 6) {
        showError('Код должен содержать 6 цифр');
        return;
    }
    
    try {
        showLoading('Авторизация...');
        const endpoint = type === 'register' ? '/api/auth/register' : '/api/auth/login';
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code })
        });
        
        const data = await response.json();
        hideLoading();
        
        if (data.success) {
            hideAuthModal();
            app.user = data.user;
            app.showUserInterface();
            app.checkAuth();
        } else {
            showError(`Ошибка: ${data.error || 'Неизвестная ошибка'}`);
        }
    } catch (error) {
        hideLoading();
        showError('Ошибка подключения');
    }
}

async function showDepositModal() {
    const modal = document.getElementById('depositModal');
    const content = document.getElementById('depositModalContent');
    
    try {
        showLoading('Получение адреса...');
        const response = await fetch('/api/wallet/deposit');
        const data = await response.json();
        hideLoading();
        
        if (data.success) {
            content.innerHTML = `
                <p>Для пополнения баланса отправьте SOL на адрес:</p>
                <div class="wallet-address">${data.address}</div>
                <div class="deposit-info">
                    <h4><i class="fas fa-info-circle"></i> Важная информация</h4>
                    <p>Этот адрес привязан к вашему Telegram аккаунту и сохраняется в системе. Отправляйте только SOL, другие активы могут быть утеряны.</p>
                </div>
                <p class="deposit-warning">
                    <i class="fas fa-exclamation-triangle"></i> Отправляйте только SOL (Solana)<br>
                    <i class="fas fa-sync-alt"></i> После отправки нажмите "Обновить баланс"
                </p>
                <div class="deposit-actions">
                    <button class="btn btn-primary" onclick="copyWalletAddress('${data.address}')">
                        <i class="fas fa-copy"></i> Скопировать адрес
                    </button>
                </div>
            `;
        } else {
            content.innerHTML = `<p class="deposit-error">Ошибка: ${data.error || 'Неизвестная ошибка'}</p>`;
        }
    } catch (error) {
        hideLoading();
        content.innerHTML = `<p class="deposit-error">Ошибка подключения</p>`;
    }
    
    modal.classList.remove('hidden');
}

function hideDepositModal() {
    document.getElementById('depositModal').classList.add('hidden');
}

function copyWalletAddress(address) {
    navigator.clipboard.writeText(address).then(() => {
        showSuccess('Адрес скопирован в буфер обмена');
    }).catch(() => {
        showError('Не удалось скопировать адрес');
    });
}

async function refreshBalance() {
    try {
        showLoading('Обновление баланса...');
        
        function getCsrfToken() {
            const value = `; ${document.cookie}`;
            const parts = value.split(`; X-CSRF-Token=`);
            if (parts.length === 2) return parts.pop().split(';').shift();
            return null;
        }
        
        const csrfToken = getCsrfToken();
        
        if (!csrfToken) {
            hideLoading();
            showError('Ошибка безопасности. Перезагрузите страницу.');
            return;
        }
        
        const response = await fetch('/api/wallet/refresh-balance', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'X-CSRF-Token': csrfToken
            }
        });
        
        const data = await response.json();
        hideLoading();
        
        if (data.success) {
            app.checkAuth();
            showSuccess('Баланс обновлен');
        } else {
            showError(`Ошибка: ${data.error || 'Неизвестная ошибка'}`);
        }
    } catch (error) {
        hideLoading();
        showError('Ошибка подключения');
    }
}

async function showWithdrawModal() {
    const modal = document.getElementById('withdrawModal');
    const content = document.getElementById('withdrawModalContent');
    
    try {
        content.innerHTML = `
            <div class="withdraw-info">
                <p>Для вывода средств укажите сумму и адрес кошелька Solana.</p>
                <p><strong>Комиссия сети:</strong> Комиссия за перевод взимается сетью Solana</p>
            </div>
            <div class="withdraw-form">
                <div class="form-group">
                    <label>Сумма (SOL):</label>
                    <input type="number" id="withdrawAmount" step="0.000001" min="0.000001" max="${app.balanceSol}" 
                           placeholder="Введите сумму" class="form-input">
                </div>
                <div class="form-group">
                    <label>Адрес кошелька Solana:</label>
                    <input type="text" id="withdrawAddress" placeholder="Введите адрес кошелька" class="form-input">
                </div>
                <div class="balance-info">
                    <p>Доступно для вывода: <strong>${app.balanceSol.toFixed(6)} SOL</strong></p>
                </div>
                <div class="modal-actions">
                    <button class="btn btn-primary" onclick="processWithdrawal()">
                        <i class="fas fa-paper-plane"></i> Вывести средства
                    </button>
                    <button class="btn btn-secondary" onclick="hideWithdrawModal()">
                        <i class="fas fa-times"></i> Отмена
                    </button>
                </div>
            </div>
        `;
    } catch (error) {
        content.innerHTML = `<p class="error-message">Ошибка загрузки формы вывода</p>`;
    }
    
    modal.classList.remove('hidden');
}

function hideWithdrawModal() {
    document.getElementById('withdrawModal').classList.add('hidden');
}

async function processWithdrawal() {
    const amount = parseFloat(document.getElementById('withdrawAmount').value);
    const address = document.getElementById('withdrawAddress').value.trim();
    
    if (!amount || amount <= 0) {
        showError('Введите корректную сумму');
        return;
    }
    
    if (amount > app.balanceSol) {
        showError('Недостаточно средств для вывода');
        return;
    }
    
    if (!address || address.length < 32) {
        showError('Введите корректный адрес кошелька Solana');
        return;
    }
    
    try {
        showLoading('Создание заявки на вывод...');
        
        const response = await fetch('/api/withdrawal/request', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                amount_sol: amount,
                wallet_address: address
            })
        });
        
        const data = await response.json();
        hideLoading();
        
        if (data.success) {
            showSuccess(`Заявка на вывод создана! Сумма: ${amount} SOL. Ожидайте подтверждения администратора.`);
            app.checkAuth();
            app.loadTransactions();
            hideWithdrawModal();
        } else {
            showError(`Ошибка: ${data.error || 'Неизвестная ошибка'}`);
        }
    } catch (error) {
        hideLoading();
        showError('Ошибка подключения');
    }
}

function startCameraScan() {
    if (app && app.qrScanner) {
        app.qrScanner.start();
    } else {
        showError('Сканер не инициализирован');
    }
}

function stopCameraScan() {
    if (app && app.qrScanner) {
        app.qrScanner.stop();
    }
}

async function processQRFile(file) {
    if (!file) return;
    
    const reader = new FileReader();
    
    reader.onload = async function(e) {
        try {
            showLoading('Загрузка...');
            
            const img = new Image();
            img.onload = function() {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                canvas.width = img.width;
                canvas.height = img.height;
                ctx.drawImage(img, 0, 0);
                
                const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
                
                const code = jsQR(imageData.data, imageData.width, imageData.height, {
                    inversionAttempts: 'dontInvert',
                });
                
                hideLoading();
                
                if (code) {
                    processQRData(code.data);
                } else {
                    showError('Не удалось распознать QR-код на изображении');
                }
            };
            
            img.onerror = function() {
                hideLoading();
                showError('Ошибка загрузки изображения');
            };
            
            img.src = e.target.result;
            
        } catch (error) {
            hideLoading();
            showError('Ошибка обработки файла');
        }
    };
    
    reader.onerror = function() {
        showError('Ошибка чтения файла');
    };
    
    reader.readAsDataURL(file);
}

async function processQRData(qrData) {
    try {
        showLoading('Обработка QR-кода...');
        
        const response = await fetch('/api/payment/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                qr_code_data: qrData
            })
        });
        
        const data = await response.json();
        hideLoading();
        
        if (data.success) {
            app.currentPayment = data;
            showPaymentModal(data);
        } else {
            showError(`Ошибка: ${data.error || 'Неизвестная ошибка'}`);
        }
    } catch (error) {
        hideLoading();
        showError('Ошибка подключения к серверу');
    }
}

function showPaymentModal(paymentData) {
    const modal = document.getElementById('paymentModal');
    const content = document.getElementById('paymentConfirmContent');
    
    const amountRub = paymentData.amount_rub || 0;
    const amountSol = (amountRub / 11350).toFixed(6);
    const description = paymentData.description || 'Оплата покупки';
    
    content.innerHTML = `
        <div class="payment-amount">${amountRub} ₽</div>
        <p class="payment-description">${description}</p>
        
        <div class="payment-details">
            <p><strong>Будет списано:</strong> ${amountSol} SOL</p>
            <p class="payment-commission">Комиссия: 10%</p>
        </div>
        
        <button class="btn btn-primary btn-pay" onclick="processPayment()">
            <i class="fas fa-credit-card"></i> Оплатить ${amountSol} SOL
        </button>

        <button class="btn btn-secondary" onclick="hidePaymentModal()">
            <i class="fas fa-times"></i> Отмена
        </button>
    `;
    
    modal.classList.remove('hidden');
}

function hidePaymentModal() {
    document.getElementById('paymentModal').classList.add('hidden');
    app.currentPayment = null;
}

function showPaymentStatus(transactionId) {
    const modal = document.getElementById('paymentStatusModal');
    const content = document.getElementById('paymentStatusContent');
    
    content.innerHTML = `
        <div class="payment-status">
            <div class="loading-spinner"></div>
            <div class="status-message">Ожидание подтверждения платежа воркером</div>
            <div class="status-info">
                <p>Средства зарезервированы на вашем балансе.</p>
                <p>Воркер получил уведомление и скоро выполнит оплату.</p>
            </div>
            <div class="status-timer">Осталось времени: <span id="paymentTimer">3:00</span></div>
        </div>
    `;
    
    modal.classList.remove('hidden');
    app.startPaymentStatusCheck(transactionId);
}

function hidePaymentStatus() {
    document.getElementById('paymentStatusModal').classList.add('hidden');
}

async function processPayment() {
    if (!app.currentPayment) {
        showError('Нет данных для оплаты');
        return;
    }
    
    try {
        showLoading('Резервирование средств...');
        
        function getCsrfToken() {
            const value = `; ${document.cookie}`;
            const parts = value.split(`; X-CSRF-Token=`);
            if (parts.length === 2) return parts.pop().split(';').shift();
            return null;
        }
        
        const csrfToken = getCsrfToken();
        
        if (!csrfToken) {
            hideLoading();
            showError('Ошибка безопасности. Перезагрузите страницу.');
            return;
        }
        
        const response = await fetch('/api/payment/process', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'X-CSRF-Token': csrfToken
            },
            body: JSON.stringify({
                amount_rub: app.currentPayment.amount_rub,
                qr_code_data: app.currentPayment.qr_data
            })
        });
        
        const data = await response.json();
        hideLoading();
        
        if (data.success) {
            hidePaymentModal();
            showPaymentStatus(data.transaction_id);
            
            app.balanceSol = data.frozen_balance;
            app.updateBalanceDisplay();
            
        } else {
            showError(`Ошибка: ${data.error || 'Неизвестная ошибка'}`);
        }
    } catch (error) {
        hideLoading();
        showError('Ошибка подключения');
    }
}

async function logout() {
    try {
        await fetch('/api/logout', { method: 'POST' });
        app.user = null;
        app.balanceSol = 0;
        app.balanceRub = 0;
        app.walletAddress = null;
        app.showAuthInterface();
    } catch (error) {
        console.error('Error logging out:', error);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    app = new CryptoPayApp();
});