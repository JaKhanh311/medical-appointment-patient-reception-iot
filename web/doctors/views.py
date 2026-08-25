from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse
from urllib.parse import urlencode
from services.RTDB_utils import (
    authenticate_doctor,
    authenticate_admin_firebase,
    get_specialty_by_id,
    get_all_doctors,
    get_all_specialties,
    get_all_appointments,
    get_homepage_news_articles,
    get_homepage_news_sections,
    get_doctor_by_id,
    get_doctors_without_account,
    create_doctor_account,
    update_doctor_account,
    provision_existing_doctor_account,
    build_doctor_patient_exam_history,
)
# Nhưng khó, dùng print trong view.


def _redirect_authenticated_user(request):
    if request.session.get('admin_portal_user_id'):
        return redirect('admin_portal_dashboard')
    if request.session.get('doctor_id'):
        return redirect('dashboard')
    return None


def _admin_required(request):
    if not request.session.get('admin_portal_user_id'):
        messages.error(request, 'Vui lòng đăng nhập admin để truy cập chức năng này.')
        return redirect('login')
    return None


def _split_lines_to_list(raw_text):
    return [line.strip() for line in (raw_text or '').splitlines() if line.strip()]


def _to_int(value, default=0):
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _to_float(value, default=0):
    try:
        return float(str(value).strip())
    except Exception:
        return default


def _build_doctor_data_from_form(request):
    specialty_id = request.POST.get('specialty_id', '').strip()
    return {
        'avatarUrl': request.POST.get('avatar_url', '').strip(),
        'awards': _split_lines_to_list(request.POST.get('awards', '')),
        'biography': request.POST.get('biography', '').strip(),
        'certifications': request.POST.get('certifications', '').strip(),
        'dateOfBirth': request.POST.get('date_of_birth', '').strip(),
        'education': request.POST.get('education', '').strip(),
        'email': request.POST.get('email', '').strip(),
        'expectedFee': _to_int(request.POST.get('expected_fee', '0'), 0),
        'experience': _to_int(request.POST.get('experience', '0'), 0),
        'gender': request.POST.get('gender', '').strip(),
        'hospitalID': request.POST.get('hospital_id', '').strip(),
        'isActive': request.POST.get('is_active') == 'on',
        'major': request.POST.get('major', '').strip(),
        'phone': request.POST.get('phone', '').strip(),
        'positions': _split_lines_to_list(request.POST.get('positions', '')),
        'publications': _split_lines_to_list(request.POST.get('publications', '')),
        'rating': _to_float(request.POST.get('rating', '0'), 0),
        'services': _split_lines_to_list(request.POST.get('services', '')),
        'specialtyID': specialty_id,
        'specialties': {specialty_id: True} if specialty_id else {},
        'techniques': _split_lines_to_list(request.POST.get('techniques', '')),
        'title': request.POST.get('title', '').strip(),
        'userID': request.POST.get('user_id', '').strip(),
        'workplaces': _split_lines_to_list(request.POST.get('workplaces', '')),
    }


def _doctor_id_sort_key(doctor):
    doctor_id = str((doctor or {}).get('id', '')).strip().lower()
    digits = ''.join(ch for ch in doctor_id if ch.isdigit())
    number = int(digits) if digits else 10**9
    return (number, doctor_id)


def home_view(request):
    all_doctors = get_all_doctors()
    specialties = get_all_specialties()
    specialty_name_map = {
        item.get('id'): item.get('name', '')
        for item in specialties
    }
    latest_articles = get_homepage_news_articles(limit=0)
    article_sections = get_homepage_news_sections(limit_per_category=0, max_sections=0)

    featured_specialties = [
        {
            'name': item.get('name', 'Chuyên khoa'),
            'description': item.get('description')
            or 'Đội ngũ bác sĩ và quy trình khám được tổ chức theo hướng theo dõi liên tục, cá nhân hóa cho từng bệnh nhân.',
        }
        for item in specialties[:12]
    ]

    # Keep enough cards so the left-sliding marquee feels continuous.
    if 0 < len(featured_specialties) < 8:
        repeat_count = (8 + len(featured_specialties) - 1) // len(featured_specialties)
        featured_specialties = (featured_specialties * repeat_count)[:8]

    featured_doctors = []
    for doctor in sorted(all_doctors, key=_doctor_id_sort_key)[:3]:
        featured_doctors.append({
            'name': doctor.get('name', 'Bác sĩ chuyên khoa'),
            'title': doctor.get('title') or 'Bác sĩ điều trị',
            'major': doctor.get('major') or specialty_name_map.get(doctor.get('specialtyID'), 'Chuyên khoa tổng quát'),
            'experience': doctor.get('experience') or 0,
            'workplace': ', '.join(doctor.get('workplaces') or []) or 'Cơ sở khám chữa bệnh trung tâm',
        })

    context = {
        'featured_specialties': featured_specialties,
        'featured_doctors': featured_doctors,
        'latest_articles': latest_articles,
        'latest_articles_per_page': 3,
        'article_sections': article_sections,
        'total_specialties': len(specialties),
        'total_doctors': len(all_doctors),
        'is_logged_in': bool(request.session.get('doctor_id') or request.session.get('admin_portal_user_id')),
    }
    return render(request, 'doctors/home.html', context)


def news_list_view(request):
    articles = get_homepage_news_articles(limit=0)
    selected_category = (request.GET.get('category') or '').strip().lower()

    categories = []
    seen_categories = set()
    for article in articles:
        category_key = (article.get('category') or 'general').strip().lower()
        if category_key in seen_categories:
            continue
        seen_categories.add(category_key)
        categories.append({
            'key': category_key,
            'label': article.get('category_display_name') or 'Tin tức',
        })

    if selected_category:
        filtered_articles = [
            article for article in articles
            if (article.get('category') or '').strip().lower() == selected_category
        ]
    else:
        filtered_articles = articles

    context = {
        'articles': filtered_articles,
        'categories': categories,
        'selected_category': selected_category,
        'total_articles': len(filtered_articles),
    }
    return render(request, 'doctors/news_list.html', context)

def login_view(request):
    if request.session.get('doctor_id'):
        return redirect('dashboard')
    if request.session.get('admin_portal_user_id'):
        return redirect('admin_portal_dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        if not username or not password:
            messages.error(request, 'Vui lòng nhập đầy đủ thông tin đăng nhập!')
            return render(request, 'doctors/login.html')

        # Thử đăng nhập bác sĩ (dùng username)
        doctor, doctor_msg = authenticate_doctor(username, password)
        if doctor:
            for key in ['admin_portal_user_id', 'admin_portal_email', 'admin_portal_name', 'admin_portal_role']:
                request.session.pop(key, None)
            request.session['doctor_id'] = doctor['id']
            request.session['doctor_name'] = doctor['name']
            doctor_specialty_id = doctor.get('specialtyID', '')
            request.session['doctor_specialty'] = doctor_specialty_id
            specialty = get_specialty_by_id(doctor_specialty_id)
            if specialty:
                request.session['specialty_name'] = specialty['name']
            messages.success(request, f'Chào mừng bác sĩ {doctor["name"]}!', extra_tags='welcome')
            return redirect('dashboard')

        # Thử đăng nhập admin (dùng email)
        ok, msg, admin_user = authenticate_admin_firebase(email=username, password=password)
        if ok and admin_user:
            for key in ['doctor_id', 'doctor_name', 'doctor_specialty', 'specialty_name']:
                request.session.pop(key, None)
            request.session['admin_portal_user_id'] = admin_user.get('uid')
            request.session['admin_portal_email'] = admin_user.get('email')
            request.session['admin_portal_name'] = admin_user.get('name')
            request.session['admin_portal_role'] = admin_user.get('role')
            messages.success(request, 'Đăng nhập quản trị thành công!')
            return redirect('admin_portal_dashboard')

        if doctor_msg:
            messages.error(request, doctor_msg)
        elif msg:
            messages.error(request, msg)
        else:
            messages.error(request, 'Tên đăng nhập/email hoặc mật khẩu không đúng!')

    return render(request, 'doctors/login.html')


def logout_view(request):
    request.session.flush()
    messages.info(request, 'Đã đăng xuất thành công!')
    return redirect('login')


def admin_portal_login_view(request):
    """Trang login admin đã được hợp nhất vào trang login chung."""
    return redirect('login')


def admin_portal_logout_view(request):
    request.session.pop('admin_portal_user_id', None)
    request.session.pop('admin_portal_email', None)
    request.session.pop('admin_portal_name', None)
    request.session.pop('admin_portal_role', None)
    messages.info(request, 'Đã đăng xuất thành công!')
    return redirect('login')


def _render_admin_dashboard_page(request):
    guard = _admin_required(request)
    if guard:
        return guard

    selected_doctor_id = request.GET.get('doctor_id', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    query = request.GET.get('q', '').strip()

    all_doctors = sorted(get_all_doctors(), key=_doctor_id_sort_key)
    specialties = get_all_specialties()
    specialty_name_map = {
        s.get('id'): s.get('name', '')
        for s in specialties
    }

    for doc in all_doctors:
        doc['specialty_name'] = specialty_name_map.get(doc.get('specialtyID'), doc.get('specialtyID', ''))

    doctors = all_doctors

    if query:
        q_lower = query.lower()
        doctors = [
            doc for doc in doctors
            if q_lower in str(doc.get('id', '')).lower()
            or q_lower in str(doc.get('name', '')).lower()
            or q_lower in str(doc.get('username', '')).lower()
            or q_lower in str(doc.get('specialty_name', '')).lower()
        ]

    exam_history = []
    if selected_doctor_id or date_from or date_to:
        exam_history = build_doctor_patient_exam_history(
            doctor_id=selected_doctor_id or None,
            date_from=date_from or None,
            date_to=date_to or None,
        )

    context = {
        'doctors': doctors,
        'doctors_for_filter': all_doctors,
        'specialties': specialties,
        'exam_history': exam_history,
        'selected_doctor_id': selected_doctor_id,
        'date_from': date_from,
        'date_to': date_to,
        'q': query,
    }
    return render(request, 'doctors/admin_dashboard.html', context)


def admin_doctor_add_view(request):
    guard = _admin_required(request)
    if guard:
        return guard

    specialties = get_all_specialties()

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        date_of_birth = request.POST.get('date_of_birth', '').strip()
        specialty_id = request.POST.get('specialty_id', '').strip()

        # Username = email, Password = ddmmyyyy from date_of_birth
        username = email
        password = ''
        if date_of_birth:
            try:
                from datetime import datetime as _dt
                # date_of_birth comes as YYYY-MM-DD from <input type="date">
                dob = _dt.strptime(date_of_birth, '%Y-%m-%d')
                password = dob.strftime('%d%m%Y')
            except (ValueError, TypeError):
                password = ''

        if not password:
            messages.error(request, 'Vui lòng nhập ngày sinh hợp lệ để tạo mật khẩu mặc định (ddmmyyyy).')
            context = {
                'specialties': specialties,
                'form_mode': 'create',
            }
            return render(request, 'doctors/admin_doctor_add.html', context)

        if not email:
            messages.error(request, 'Vui lòng nhập email để làm tài khoản đăng nhập.')
            context = {
                'specialties': specialties,
                'form_mode': 'create',
            }
            return render(request, 'doctors/admin_doctor_add.html', context)

        doctor_data = _build_doctor_data_from_form(request)
        ok, message, created = create_doctor_account(
            name=full_name,
            username=username,
            password=password,
            specialty_id=specialty_id,
            doctor_data=doctor_data,
        )

        if ok:
            messages.success(request, f'{message} (Tài khoản: {email} / Mật khẩu: {password})')
            return redirect('admin_doctor_edit', doctor_id=created.get('id', ''))

        messages.error(request, message)

    context = {
        'specialties': specialties,
        'form_mode': 'create',
    }
    return render(request, 'doctors/admin_doctor_add.html', context)


def admin_doctor_edit_view(request, doctor_id):
    guard = _admin_required(request)
    if guard:
        return guard

    doctor_id = (doctor_id or '').strip()
    doctor = get_doctor_by_id(doctor_id)
    if not doctor:
        messages.error(request, 'Không tìm thấy bác sĩ cần chỉnh sửa.')
        return redirect('admin_portal_dashboard')

    specialties = get_all_specialties()

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        specialty_id = request.POST.get('specialty_id', '').strip()
        new_password = request.POST.get('new_password', '').strip()

        # Username is read-only in edit page.
        username = str(doctor.get('username', '')).strip()
        doctor_data = _build_doctor_data_from_form(request)

        ok, message, updated = update_doctor_account(
            doctor_id=doctor_id,
            name=full_name,
            username=username,
            specialty_id=specialty_id,
            password=new_password,
            doctor_data=doctor_data,
        )

        if ok:
            messages.success(request, message)
            doctor = updated or doctor
        else:
            messages.error(request, message)

    context = {
        'doctor': doctor,
        'specialties': specialties,
        'form_mode': 'edit',
    }
    return render(request, 'doctors/admin_doctor_edit.html', context)


def admin_doctor_history_view(request, doctor_id):
    guard = _admin_required(request)
    if guard:
        return guard

    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

    doctor_id = (doctor_id or '').strip()
    doctor = get_doctor_by_id(doctor_id)
    if not doctor:
        messages.error(request, 'Không tìm thấy bác sĩ để xem lịch sử khám.')
        return redirect('admin_portal_dashboard')

    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()

    # Cache key per doctor + date range — reuse on pagination (page 2, 3, ...)
    cache_key = f"admin_history:{doctor_id}:{date_from}:{date_to}"
    from django.core.cache import cache
    exam_history = cache.get(cache_key)
    if exam_history is None:
        exam_history = build_doctor_patient_exam_history(
            doctor_id=doctor_id,
            date_from=date_from or None,
            date_to=date_to or None,
        )
        cache.set(cache_key, exam_history, 60)  # cache 60s for pagination

    unique_patients = len({row.get('patient_id', '') for row in exam_history if row.get('patient_id')})
    unique_dates = len({row.get('date', '') for row in exam_history if row.get('date')})

    # Phân trang: 10 records / trang
    paginator = Paginator(exam_history, 10)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)

    context = {
        'doctor': doctor,
        'exam_history': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'is_paginated': page_obj.has_other_pages(),
        'date_from': date_from,
        'date_to': date_to,
        'history_stats': {
            'total_exams': len(exam_history),
            'total_patients': unique_patients,
            'total_days': unique_dates,
        },
    }
    return render(request, 'doctors/admin_doctor_history.html', context)


def admin_doctor_provision_view(request):
    """Đổi mật khẩu bác sĩ — admin chọn bác sĩ và đặt mật khẩu mới."""
    guard = _admin_required(request)
    if guard:
        return guard

    all_doctors = sorted(get_all_doctors(), key=_doctor_id_sort_key)
    selected_doctor_id = request.GET.get('doctor_id', '').strip()
    selected_doctor = None

    if selected_doctor_id:
        selected_doctor = next(
            (doc for doc in all_doctors if str(doc.get('id', '')).strip() == selected_doctor_id),
            None,
        )

    if request.method == 'POST':
        doctor_id = request.POST.get('doctor_id', '').strip()
        new_password = request.POST.get('new_password', '').strip()

        if not doctor_id:
            messages.error(request, 'Thiếu mã bác sĩ.')
        elif not new_password or len(new_password) < 6:
            messages.error(request, 'Mật khẩu mới phải từ 6 ký tự trở lên.')
            selected_doctor = get_doctor_by_id(doctor_id)
        else:
            doctor = get_doctor_by_id(doctor_id)
            if not doctor:
                messages.error(request, 'Không tìm thấy bác sĩ.')
            else:
                ok, message, _updated = update_doctor_account(
                    doctor_id=doctor_id,
                    name=doctor.get('name', ''),
                    username=doctor.get('username', ''),
                    specialty_id=doctor.get('specialtyID', ''),
                    password=new_password,
                    doctor_data=doctor,
                )
                if ok:
                    messages.success(request, f'Đã đổi mật khẩu thành công cho bác sĩ {doctor.get("name", "")}.')
                    return redirect('admin_portal_dashboard')
                else:
                    messages.error(request, message)
                    selected_doctor = doctor

    context = {
        'doctors_without_account': all_doctors,
        'selected_doctor': selected_doctor,
        'selected_doctor_id': selected_doctor_id,
    }
    return render(request, 'doctors/admin_doctor_provision.html', context)


def admin_portal_dashboard_view(request):
    return _render_admin_dashboard_page(request)


def admin_statistics_view(request):
    """Trang thống kê lịch hẹn cho admin."""
    guard = _admin_required(request)
    if guard:
        return guard

    # Load filter params
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    filter_specialty = request.GET.get('specialty', '').strip()
    filter_doctor = request.GET.get('doctor', '').strip()

    # Load all appointments
    all_appointments = get_all_appointments()

    # Build name lookup maps for display
    specialties = get_all_specialties()
    doctors = get_all_doctors()
    specialty_name_map = {s.get('id', ''): s.get('name', '') for s in specialties}
    doctor_name_map = {d.get('id', ''): d.get('name', '') for d in doctors}

    # Apply filters
    filtered = all_appointments
    if date_from:
        filtered = [a for a in filtered if (a.get('date') or '') >= date_from]
    if date_to:
        filtered = [a for a in filtered if (a.get('date') or '') <= date_to]
    if filter_specialty:
        filtered = [a for a in filtered if a.get('specialtyID') == filter_specialty]
    if filter_doctor:
        filtered = [a for a in filtered if a.get('doctorID') == filter_doctor]

    # Status counts
    total = len(filtered)
    completed = sum(1 for a in filtered if str(a.get('status', '')).lower() in ('complete', 'completed'))
    cancelled = sum(1 for a in filtered if str(a.get('status', '')).lower() == 'cancelled')
    no_show = sum(1 for a in filtered if str(a.get('status', '')).lower() == 'no_show')
    waiting = sum(1 for a in filtered if str(a.get('status', '')).lower() in ('waiting', 'arrived'))
    scheduled = sum(1 for a in filtered if str(a.get('status', '')).lower() == 'scheduled')

    # Breakdown by specialty — show NAME not ID
    specialty_counts = {}
    for a in filtered:
        spec_id = a.get('specialtyID') or ''
        spec_name = specialty_name_map.get(spec_id) or a.get('specialtyName') or spec_id or 'Không rõ'
        specialty_counts[spec_name] = specialty_counts.get(spec_name, 0) + 1
    specialty_breakdown = sorted(specialty_counts.items(), key=lambda x: x[1], reverse=True)
    max_specialty_count = specialty_breakdown[0][1] if specialty_breakdown else 1

    # Breakdown by doctor — show NAME not ID
    doctor_counts = {}
    for a in filtered:
        doc_id = a.get('doctorID') or ''
        doc_name = doctor_name_map.get(doc_id) or a.get('doctorName') or doc_id or 'Không rõ'
        doctor_counts[doc_name] = doctor_counts.get(doc_name, 0) + 1
    doctor_breakdown = sorted(doctor_counts.items(), key=lambda x: x[1], reverse=True)
    max_doctor_count = doctor_breakdown[0][1] if doctor_breakdown else 1

    # Time distribution
    morning_count = sum(1 for a in filtered if str(a.get('session', '')).lower() == 'morning')
    afternoon_count = sum(1 for a in filtered if str(a.get('session', '')).lower() == 'afternoon')
    time_total = morning_count + afternoon_count or 1

    # Dropdown data
    specialties = get_all_specialties()
    doctors = get_all_doctors()

    context = {
        'date_from': date_from,
        'date_to': date_to,
        'filter_specialty': filter_specialty,
        'filter_doctor': filter_doctor,
        'total': total,
        'completed': completed,
        'cancelled': cancelled,
        'no_show': no_show,
        'waiting': waiting,
        'scheduled': scheduled,
        'specialty_breakdown': specialty_breakdown,
        'max_specialty_count': max_specialty_count,
        'doctor_breakdown': doctor_breakdown,
        'max_doctor_count': max_doctor_count,
        'morning_count': morning_count,
        'afternoon_count': afternoon_count,
        'time_total': time_total,
        'specialties': specialties,
        'doctors': doctors,
    }
    return render(request, 'doctors/admin_statistics.html', context)
