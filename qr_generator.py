"""
Модуль для генерации и обработки QR-кодов
"""

import qrcode
import base64
import io
import re
from typing import Dict, Optional

class QRCodeManager:
    
    @staticmethod
    def generate_payment_qr(amount_rub: float, description: str = "Оплата покупки") -> Dict:
        """
        Генерировать QR-код для оплаты с ПРАВИЛЬНОЙ суммой
        """
        try:
            amount_kopecks = int(amount_rub * 100)
            qr_data = f"ST00012|Name=Оплата товара|Sum={amount_kopecks}|Purpose={description}"
            
            print(f"🔢 Генерация QR: {amount_rub} руб = {amount_kopecks} копеек")
            
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=20,
                border=4,
            )
            
            qr.add_data(qr_data)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            
            qr_image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
            return {
                'success': True,
                'qr_data': qr_data,
                'qr_image': qr_image_base64,
                'amount_rub': amount_rub,
                'description': description
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Ошибка генерации QR-кода: {str(e)}'
            }
    
    @staticmethod
    def parse_qr_data(qr_data: str) -> Dict:
        try:
            if not qr_data or len(qr_data) > 1000:
                return {'valid': False, 'error': 'Неверные данные QR-кода'}
            
            qr_data = qr_data.strip()
            
            if qr_data.startswith('ST00012'):
                return QRCodeManager._parse_sbp_format(qr_data)
            elif '|' in qr_data:
                return QRCodeManager._parse_pipe_format(qr_data)
            elif qr_data.startswith('https://') or qr_data.startswith('http://'):
                return QRCodeManager._parse_url_format(qr_data)
            else:
                return QRCodeManager._parse_unknown_format(qr_data)
                
        except Exception as e:
            return {
                'valid': False,
                'error': 'Ошибка обработки QR-кода'
            }
    
    @staticmethod
    def _parse_sbp_format(qr_data: str) -> Dict:
        """Парсинг формата СБП с ПРАВИЛЬНЫМ расчетом суммы"""
        try:
            parts = qr_data.split('|')
            result = {'valid': True, 'format': 'sbp'}
            
            for part in parts:
                if part.startswith('Sum='):
                    amount_kopecks = int(part.replace('Sum=', ''))
                    result['amount_rub'] = amount_kopecks / 100
                    print(f"🔍 Парсинг QR: {amount_kopecks} коп = {result['amount_rub']} руб")
                elif part.startswith('Name='):
                    result['description'] = part.replace('Name=', '')
                elif part.startswith('Purpose='):
                    result['description'] = part.replace('Purpose=', '')
            
            if 'amount_rub' not in result:
                return {'valid': False, 'error': 'Не найдена сумма в QR-коде'}
            
            if 'description' not in result:
                result['description'] = 'Оплата покупки'
                
            return result
            
        except Exception as e:
            return {'valid': False, 'error': f'Ошибка парсинга СБП формата: {str(e)}'}
    
    @staticmethod
    def _parse_pipe_format(qr_data: str) -> Dict:
        """Парсинг формата с разделителями |"""
        try:
            parts = qr_data.split('|')
            result = {'valid': True, 'format': 'pipe'}
            
            for part in parts:
                if '=' in part:
                    key, value = part.split('=', 1)
                    if key.lower() in ['sum', 'amount', 'total']:
                        try:
                            amount = float(value)
                            if amount > 1000:
                                result['amount_rub'] = amount / 100
                            else:
                                result['amount_rub'] = amount
                        except:
                            pass
                    elif key.lower() in ['desc', 'description', 'purpose']:
                        result['description'] = value
            
            if 'amount_rub' not in result:
                numbers = re.findall(r'\d+\.?\d*', qr_data)
                if numbers:
                    amount = float(numbers[0])
                    if amount > 1000:
                        result['amount_rub'] = amount / 100
                    else:
                        result['amount_rub'] = amount
            
            if 'amount_rub' not in result:
                return {'valid': False, 'error': 'Не найдена сумма в QR-коде'}
            
            if 'description' not in result:
                result['description'] = 'Оплата покупки'
                
            return result
            
        except Exception as e:
            return {'valid': False, 'error': f'Ошибка парсинга pipe формата: {str(e)}'}
    
    @staticmethod
    def _parse_url_format(qr_data: str) -> Dict:
        try:
            from urllib.parse import urlparse, parse_qs
            
            parsed = urlparse(qr_data)
            
            allowed_domains = ['qr.nspk.ru', 'sberbank.ru', 'tinkoff.ru', 'sbp.nspk.ru']
            if parsed.netloc not in allowed_domains:
                return {'valid': False, 'error': 'Недопустимый домен в QR-коде'}
            
            params = parse_qs(parsed.query)
            result = {'valid': True, 'format': 'url'}
            
            amount_keys = ['amount', 'sum', 'total', 'amt']
            for key in amount_keys:
                if key in params and params[key]:
                    try:
                        amount = float(params[key][0])
                        if 1 <= amount <= 100000:
                            if amount > 1000:
                                result['amount_rub'] = amount / 100
                            else:
                                result['amount_rub'] = amount
                            break
                    except:
                        continue
            
            if 'amount_rub' not in result:
                return {'valid': False, 'error': 'Не найдена сумма в QR-коде'}
            
            result['description'] = 'Оплата покупки'
            return result
            
        except Exception as e:
            return {'valid': False, 'error': 'Ошибка обработки URL'}
    
    @staticmethod
    def _parse_unknown_format(qr_data: str) -> Dict:
        """Парсинг неизвестного формата"""
        try:
            result = {'valid': True, 'format': 'unknown'}
            
            numbers = re.findall(r'\d+\.?\d*', qr_data)
            if numbers:
                for num in numbers:
                    amount = float(num)
                    if 1 <= amount <= 100000:
                        if amount > 1000:
                            result['amount_rub'] = amount / 100
                        else:
                            result['amount_rub'] = amount
                        break
            
            if 'amount_rub' not in result:
                return {'valid': False, 'error': 'Не найдена сумма в QR-коде'}
            
            if len(qr_data) > 50:
                result['description'] = qr_data[:50] + '...'
            else:
                result['description'] = qr_data
                
            return result
            
        except Exception as e:
            return {'valid': False, 'error': f'Ошибка парсинга неизвестного формата: {str(e)}'}
    
    @staticmethod
    def validate_qr_data(qr_data: str) -> bool:
        """Проверить валидность данных QR-кода"""
        parsed = QRCodeManager.parse_qr_data(qr_data)
        return parsed['valid']