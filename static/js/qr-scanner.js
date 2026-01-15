class QRScanner {
    constructor() {
        this.stream = null;
        this.isScanning = false;
        this.video = document.getElementById('qrScanner');
        this.canvas = document.getElementById('qrCanvas');
        this.context = this.canvas.getContext('2d');
    }

    async start() {
        try {
            this.stream = await navigator.mediaDevices.getUserMedia({ 
                video: { 
                    facingMode: 'environment',
                    width: { ideal: 1280 },
                    height: { ideal: 720 }
                } 
            });
            
            this.video.srcObject = this.stream;
            this.video.play();
            this.isScanning = true;
            
            this.scanFrame();
            
            return true;
        } catch (error) {
            console.error('Error accessing camera:', error);
            return false;
        }
    }

    stop() {
        this.isScanning = false;
        
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }
        
        if (this.video.srcObject) {
            this.video.srcObject = null;
        }
    }

    scanFrame() {
        if (!this.isScanning) return;
        
        if (this.video.readyState === this.video.HAVE_ENOUGH_DATA) {
            this.canvas.width = this.video.videoWidth;
            this.canvas.height = this.video.videoHeight;
            
            this.context.drawImage(this.video, 0, 0, this.canvas.width, this.canvas.height);

            this.simulateQRDetection();
        }
        
        requestAnimationFrame(() => this.scanFrame());
    }

    simulateQRDetection() {
        if (Math.random() < 0.1) {
            this.onQRDetected('ST00012|Name=Оплата товара|Sum=10000|Purpose=Оплата покупки');
        }
    }

    onQRDetected(qrData) {
        console.log('QR Code detected:', qrData);
        
        this.processQRCode(qrData);
    }

    async processQRCode(qrData) {
        try {
            const response = await fetch('/api/payment/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    qr_code_data: qrData,
                    qr_code_image: this.canvas.toDataURL().split(',')[1]
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.showSuccess('Платеж отправлен на обработку!');
                this.stop();
                hideScanModal();
            } else {
                this.showError('Ошибка: ' + data.error);
            }
        } catch (error) {
            this.showError('Ошибка подключения');
        }
    }

    showSuccess(message) {
        alert('✅ ' + message);
    }

    showError(message) {
        alert('❌ ' + message);
    }
}

const qrScanner = new QRScanner();