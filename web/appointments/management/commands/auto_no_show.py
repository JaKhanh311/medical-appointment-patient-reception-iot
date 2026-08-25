"""
Management command: Tự động đánh dấu no_show cho appointments quá hạn.

Chạy thủ công:
    python manage.py auto_no_show

Chạy tự động (Windows Task Scheduler hoặc cron):
    - Lúc 12:05 mỗi ngày: đánh dấu buổi sáng
    - Lúc 17:05 mỗi ngày: đánh dấu buổi chiều
    
Hoặc chạy 1 lần cuối ngày (23:00) để đánh dấu cả 2 buổi.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from services.RTDB_utils import mark_scheduled_appointments_no_show, get_all_doctors


class Command(BaseCommand):
    help = 'Tự động đánh dấu no_show cho appointments chưa check-in khi buổi khám đã kết thúc.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            default='',
            help='Ngày cần xử lý (YYYY-MM-DD). Mặc định: hôm nay.',
        )
        parser.add_argument(
            '--session',
            type=str,
            default='',
            choices=['morning', 'afternoon', ''],
            help='Buổi cần xử lý. Mặc định: tự động theo giờ hiện tại.',
        )
        parser.add_argument(
            '--doctor',
            type=str,
            default='',
            help='Chỉ xử lý cho 1 bác sĩ (doctor_id). Mặc định: tất cả.',
        )

    def handle(self, *args, **options):
        now = timezone.localtime()
        target_date = options['date'] or now.date().isoformat()
        session = options['session']
        doctor_id = options['doctor']

        # Determine which sessions to process
        sessions_to_process = []
        if session:
            sessions_to_process = [session]
        else:
            current_hour = now.hour
            if current_hour >= 12:
                sessions_to_process.append('morning')
            if current_hour >= 17:
                sessions_to_process.append('afternoon')
            # If running for a past date, process both
            if target_date < now.date().isoformat():
                sessions_to_process = ['morning', 'afternoon']

        if not sessions_to_process:
            self.stdout.write(self.style.WARNING(
                f'Chưa đến giờ đóng buổi nào (hiện tại: {now.strftime("%H:%M")}). '
                f'Buổi sáng đóng lúc 12:00, buổi chiều đóng lúc 17:00.'
            ))
            return

        # Get doctors to process
        if doctor_id:
            doctor_ids = [doctor_id]
        else:
            doctors = get_all_doctors()
            doctor_ids = [str(d.get('id', '')).strip() for d in doctors if d.get('id')]

        self.stdout.write(f'Ngày: {target_date}')
        self.stdout.write(f'Buổi: {", ".join(sessions_to_process)}')
        self.stdout.write(f'Bác sĩ: {len(doctor_ids)} người')
        self.stdout.write('---')

        total_updated = 0
        for doc_id in doctor_ids:
            for sess in sessions_to_process:
                count = mark_scheduled_appointments_no_show(target_date, sess, doc_id)
                if count > 0:
                    self.stdout.write(f'  {doc_id} / {sess}: {count} no_show')
                    total_updated += count

        if total_updated:
            self.stdout.write(self.style.SUCCESS(f'\nTổng: {total_updated} appointments đã chuyển no_show.'))
        else:
            self.stdout.write(self.style.SUCCESS('\nKhông có appointment nào cần đánh dấu no_show.'))
