from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.db.models import Max, Min, Q, Sum
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import Category, Transaction, Budget, SavingsGoal, SavingsTransaction
from .forms import TransactionForm, SavingsGoalForm, SavingsTransactionForm, UserProfileForm
from datetime import datetime
from decimal import Decimal
import json
from datetime import timedelta
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db.models.functions import TruncDay, TruncMonth
from django.contrib.auth.models import User


def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect("dashboard")
        else:
            return render(request, "login.html", {"error": "Invalid credentials"})

    return render(request, "login.html")


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def dashboard(request):
    return render(request, 'dashboard.html', {
        'dashboard_data': get_dashboard_data(request.user),
    })

@login_required
def transactions_view(request):
    return render(request, 'transactions.html')

@login_required
def goals_view(request):
    return render(request, 'goals.html')


def get_dashboard_data(user):
    transactions = Transaction.objects.filter(user=user)
    totals = transactions.aggregate(
        total_income=Sum(
            'amount',
            filter=Q(transaction_type=Transaction.TransactionType.INCOME),
        ),
        total_expense=Sum(
            'amount',
            filter=Q(transaction_type=Transaction.TransactionType.EXPENSE),
        ),
    )
    total_income = totals['total_income'] or Decimal('0.00')
    total_expense = totals['total_expense'] or Decimal('0.00')
    net_savings = total_income - total_expense

    expense_transactions = transactions.filter(
        transaction_type=Transaction.TransactionType.EXPENSE,
    )
    category_totals = {}
    for row in expense_transactions.filter(
        category__user=user,
    ).values('category__name').annotate(total=Sum('amount')).order_by('category__name'):
        category_name = row['category__name'] or 'Other'
        category_totals[category_name] = category_totals.get(
            category_name,
            Decimal('0.00'),
        ) + row['total']
    other_expense_total = expense_transactions.filter(
        Q(category__isnull=True)
        | (Q(category__user__isnull=False) & ~Q(category__user=user))
    ).aggregate(total=Sum('amount'))['total']
    if other_expense_total is not None:
        category_totals['Other'] = category_totals.get(
            'Other',
            Decimal('0.00'),
        ) + other_expense_total

    today = timezone.localdate()
    budget = Budget.objects.filter(
        user=user,
        month=today.month,
        year=today.year,
    ).first()
    current_month_expense = transactions.filter(
        transaction_type=Transaction.TransactionType.EXPENSE,
        date__year=today.year,
        date__month=today.month,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    budget_warning = None
    if budget:
        if current_month_expense > budget.monthly_limit:
            budget_warning = '⚠ You have exceeded your monthly budget!'
        elif current_month_expense > budget.monthly_limit * Decimal('0.8'):
            budget_warning = '⚠ Warning: You are close to your budget limit.'

    recent_transactions = []
    for transaction in transactions.select_related('category').order_by(
        '-date', '-created_at', '-id'
    )[:10]:
        if transaction.category_id:
            category_name = (
                transaction.category.name
                if transaction.category.user_id == user.pk
                else 'Other'
            )
        else:
            category_name = transaction.merchant or 'Other'
        recent_transactions.append({
            'id': transaction.pk,
            'date': transaction.date.isoformat(),
            'category_id': transaction.category_id,
            'category': category_name,
            'category_type': transaction.transaction_type,
            'amount': float(transaction.amount),
        })

    return {
        'total_income': float(total_income),
        'total_expense': float(total_expense),
        'net_savings': float(net_savings),
        'balance': float(net_savings),
        'budget_warning': budget_warning,
        'labels': list(category_totals),
        'data': [float(amount) for amount in category_totals.values()],
        'recent_transactions': recent_transactions,
        'tx_count': transactions.count(),
    }


@login_required
def api_dashboard_data(request):
    return JsonResponse(get_dashboard_data(request.user))


# ─── AJAX: Summary data ────────────────────────────────────────────────
@login_required
def api_summary(request):
    transactions = Transaction.objects.filter(user=request.user)

    total_income = transactions.filter(
        transaction_type=Transaction.TransactionType.INCOME
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    total_expense = transactions.filter(
        transaction_type=Transaction.TransactionType.EXPENSE
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    balance = float(total_income) - float(total_expense)

    today = datetime.today()
    budget = Budget.objects.filter(
        user=request.user,
        month=today.month,
        year=today.year
    ).first()

    budget_warning = None
    if budget:
        if total_expense > budget.monthly_limit:
            budget_warning = "⚠ You have exceeded your monthly budget!"
        elif total_expense > (budget.monthly_limit * Decimal('0.8')):
            budget_warning = "⚠ Warning: You are close to your budget limit."

    expense_categories = transactions.filter(
        transaction_type=Transaction.TransactionType.EXPENSE,
        category__isnull=False,
    ).values('category__name').annotate(total=Sum('amount'))

    labels = [item['category__name'] for item in expense_categories]
    data = [float(item['total']) for item in expense_categories]

    return JsonResponse({
        'total_income': float(total_income),
        'total_expense': float(total_expense),
        'balance': balance,
        'budget_warning': budget_warning,
        'labels': labels,
        'data': data,
    })


# ─── AJAX: Transactions list ───────────────────────────────────────────
@login_required
def api_transactions(request):
    transactions = Transaction.objects.filter(user=request.user).order_by('-date', '-created_at', '-id')
    category_type = request.GET.get('type')
    if category_type:
        if category_type not in {'income', 'expense'}:
            return JsonResponse({'error': 'type must be income or expense'}, status=400)
        transactions = transactions.filter(transaction_type=category_type)

    limit = request.GET.get('limit')
    if limit is not None:
        try:
            limit = int(limit)
        except ValueError:
            return JsonResponse({'error': 'limit must be a positive integer'}, status=400)
        if limit < 1:
            return JsonResponse({'error': 'limit must be a positive integer'}, status=400)
        transactions = transactions[:limit]

    result = []
    for t in transactions:
        result.append({
            'id': t.pk,
            'date': str(t.date),
            'category_id': t.category_id,
            'category': t.category.name if t.category_id else (t.merchant or 'Uncategorized'),
            'category_type': t.transaction_type,
            'amount': float(t.amount),
        })
    return JsonResponse({'transactions': result})


# ─── AJAX: Goals list ─────────────────────────────────────────────────
@login_required
def api_goals(request):
    try:
        goals = SavingsGoal.objects.filter(user=request.user)
        result = []
        for g in goals:
            history = []
            for st in g.transactions.order_by('-date', '-id'):
                history.append({'amount': float(st.amount), 'date': str(st.date)})
            saved = float(g.saved_amount)
            target = float(g.target_amount)
            progress = round(g.progress_percentage, 1)
            result.append({
                'id': g.id,
                'title': g.title,
                'target_amount': target,
                'saved_amount': saved,
                'progress_percentage': progress,
                'deadline': str(g.deadline),
                'history': history,
            })
        return JsonResponse({'goals': result})
    except Exception as e:
        import traceback
        print("API GOALS ERROR: ", traceback.format_exc())
        return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)


# ─── AJAX: Progress Stats ─────────────────────────────────────────────
@login_required
def api_progress(request):
    today = datetime.today()
    this_month = today.month
    this_year = today.year
    
    # Calculate last month
    if this_month == 1:
        last_month = 12
        last_month_year = this_year - 1
    else:
        last_month = this_month - 1
        last_month_year = this_year
        
    # Get all users who had savings transactions last month
    last_month_savers = SavingsTransaction.objects.filter(
        date__month=last_month,
        date__year=last_month_year
    ).values('user').distinct().count()
    
    # Get all users who had savings transactions this month
    this_month_savers = SavingsTransaction.objects.filter(
        date__month=this_month,
        date__year=this_year
    ).values('user').distinct().count()
    
    total_users = User.objects.count()
    
    last_month_pct = round((last_month_savers / total_users * 100), 1) if total_users > 0 else 0
    this_month_pct = round((this_month_savers / total_users * 100), 1) if total_users > 0 else 0
    
    # Calculate current user's goal progress this month
    user_savings_this_month = SavingsTransaction.objects.filter(
        user=request.user,
        date__month=this_month,
        date__year=this_year
    ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    
    # 3) Auto Completion Logic before calculating active goals
    user_goals = SavingsGoal.objects.filter(user=request.user)
    for g in user_goals:
        goal_saved = g.saved_amount
        if goal_saved >= g.target_amount and not g.is_completed:
            g.is_completed = True
            g.save(update_fields=['is_completed'])
            
    # 1) Active Goals calculation
    active_goals = user_goals.filter(is_completed=False).count()
            
    # 2) Goal Progress Calculation (Advanced Logic)
    # Using Django ORM safely to calculate totals
    aggregates = user_goals.aggregate(
        total_target=Sum('target_amount'),
        total_saved=Sum('transactions__amount')
    )
    
    total_target = aggregates['total_target'] or Decimal('0.00')
    total_saved = aggregates['total_saved'] or Decimal('0.00')
    
    if total_target > Decimal('0.00') and user_goals.exists():
        user_progress_pct = round(float((total_saved / total_target) * 100), 1)
    else:
        user_progress_pct = 0.0

    # 4) Debug Mode Prints
    total_goals_count = user_goals.count()
    print("--- Goal Progress Debug ---")
    print("Total Goals:", total_goals_count)
    print("Active Goals:", active_goals)
    print("Total Saved:", total_saved)
    print("Total Target:", total_target)
    print("Final Progress:", user_progress_pct)

    return JsonResponse({
        'community_last_month': last_month_pct,
        'community_this_month': this_month_pct,
        'user_savings_this_month': float(user_savings_this_month),
        'user_progress_pct': user_progress_pct,
        'active_goals': active_goals
    })


# ─── Add Transaction (AJAX) ───────────────────────────────────────────
@login_required
def add_transaction(request):
    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.user = request.user
            transaction.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            return redirect('dashboard')
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': form.errors}, status=400)
    else:
        form = TransactionForm()

    return render(request, 'add_transaction.html', {'form': form})


# ─── Edit Transaction (AJAX) ──────────────────────────────────────────
@login_required
def edit_transaction(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, user=request.user)

    if request.method == 'POST':
        form = TransactionForm(request.POST, instance=transaction)
        if form.is_valid():
            form.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            return redirect('dashboard')
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': form.errors}, status=400)
    else:
        form = TransactionForm(instance=transaction)

    return render(request, 'add_transaction.html', {'form': form, 'edit_mode': True, 'pk': pk})


# ─── Delete Transaction (AJAX) ────────────────────────────────────────
@login_required
def delete_transaction(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, user=request.user)
    transaction.delete()
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    return redirect('dashboard')

@login_required
def delete_transaction_ajax(request, pk):
    """POST-only AJAX delete endpoint."""
    if request.method == 'POST':
        transaction = get_object_or_404(Transaction, pk=pk, user=request.user)
        transaction.delete()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False}, status=405)


# ─── Add Goal (AJAX) ──────────────────────────────────────────────────
@login_required
def add_goal(request):
    if request.method == 'POST':
        form = SavingsGoalForm(request.POST)
        if form.is_valid():
            goal = form.save(commit=False)
            goal.user = request.user
            goal.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            return redirect('dashboard')
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': form.errors}, status=400)
    else:
        form = SavingsGoalForm()
    return render(request, 'add_goal.html', {'form': form})


@login_required
@require_POST
def delete_goal(request, goal_id):
    goal = get_object_or_404(SavingsGoal, id=goal_id, user=request.user)
    goal.delete()
    return JsonResponse({'success': True})


# ─── Add Savings (AJAX) ───────────────────────────────────────────────
@login_required
def add_savings(request, goal_id):
    goal = get_object_or_404(SavingsGoal, id=goal_id, user=request.user)

    if request.method == "POST":
        amount = Decimal(request.POST.get("amount"))
        SavingsTransaction.objects.create(
            goal=goal,
            user=request.user,
            amount=amount
        )
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        return redirect("dashboard")

    return render(request, "add_savings.html", {"goal": goal})


# ─── Withdraw Savings (AJAX) ──────────────────────────────────────────
@login_required
def withdraw_savings(request, goal_id):
    goal = get_object_or_404(SavingsGoal, id=goal_id, user=request.user)

    if request.method == "POST":
        form = SavingsTransactionForm(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.goal = goal
            transaction.user = request.user
            transaction.amount = -abs(transaction.amount)
            transaction.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            return redirect('dashboard')
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': form.errors}, status=400)
    else:
        form = SavingsTransactionForm()

    return render(request, 'add_savings.html', {
        'form': form,
        'goal': goal,
        'is_withdraw': True
    })


# ─── Profile view & edit ──────────────────────────────────────────────
@login_required
def profile_view(request):
    return render(request, 'profile.html', {'user': request.user})


@login_required
def profile_edit(request):
    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'Profile updated successfully!'})
            return redirect('profile')
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': form.errors}, status=400)
    else:
        form = UserProfileForm(instance=request.user)
    return render(request, 'profile.html', {'form': form, 'edit_mode': True})
# views.py


@login_required
def expense_data_api(request):
    time_filter = request.GET.get('filter', 'last_30_days')
    today = timezone.localdate()
    
    if time_filter == 'last_7_days':
        start_date = today - timedelta(days=7)
    elif time_filter == 'last_6_months':
        # Approx 6 months
        start_date = today - timedelta(days=180)
    else:
        start_date = today - timedelta(days=30)
        
    base_qs = Transaction.objects.filter(
        user=request.user,
        transaction_type=Transaction.TransactionType.EXPENSE,
        date__gte=start_date
    )
    
    daily_qs = (base_qs
                .annotate(day=TruncDay('date'))
                .values('day')
                .annotate(total=Sum('amount'))
                .order_by('day'))
                
    monthly_qs = (base_qs
                  .annotate(month=TruncMonth('date'))
                  .values('month')
                  .annotate(total=Sum('amount'))
                  .order_by('month'))

    daily_filter = request.GET.get('daily_filter', 'last_30_days')
    daily_start = None
    daily_end = today
    if daily_filter == 'last_7_days':
        daily_start = today - timedelta(days=6)
    elif daily_filter == 'last_30_days':
        daily_start = today - timedelta(days=29)
    elif daily_filter == 'this_month':
        daily_start = today.replace(day=1)
    elif daily_filter == 'all_days':
        all_expenses = Transaction.objects.filter(
            user=request.user,
            transaction_type=Transaction.TransactionType.EXPENSE,
        ).aggregate(first_date=Min('date'), last_date=Max('date'))
        daily_start = all_expenses['first_date']
        daily_end = all_expenses['last_date'] or today
    elif daily_filter == 'custom':
        daily_start = parse_date(request.GET.get('start_date', ''))
        daily_end = parse_date(request.GET.get('end_date', ''))
        if not daily_start or not daily_end:
            return JsonResponse(
                {'error': 'Custom date ranges require valid start_date and end_date values.'},
                status=400,
            )
        if daily_start > daily_end:
            return JsonResponse(
                {'error': 'start_date must be on or before end_date.'},
                status=400,
            )
    else:
        return JsonResponse({'error': 'Unsupported daily date range.'}, status=400)

    all_expense_categories = Category.objects.filter(
        user=request.user,
        category_type='expense',
    ).order_by('name', 'id')
    expense_categories = all_expense_categories
    category_id = request.GET.get('category', '')
    if category_id:
        if category_id == 'uncategorized':
            expense_categories = Category.objects.none()
        elif not category_id.isdigit():
            return JsonResponse({'error': 'category must be a valid expense category.'}, status=400)
        else:
            expense_categories = expense_categories.filter(pk=category_id)
        if category_id != 'uncategorized' and not expense_categories.exists():
            return JsonResponse({'error': 'category must be a valid expense category.'}, status=400)

    daily_datasets = []
    daily_labels = []
    daily_totals = []
    if daily_start:
        daily_totals = (
            Transaction.objects.filter(
                user=request.user,
                transaction_type=Transaction.TransactionType.EXPENSE,
                date__gte=daily_start,
                date__lte=daily_end,
            )
            .filter(Q(category__in=all_expense_categories) | Q(category__isnull=True))
            .values('date', 'category_id', 'category__name')
            .annotate(total=Sum('amount'))
            .order_by('date', 'category__name', 'category_id')
        )
        daily_labels = sorted({row['date'].isoformat() for row in daily_totals})
        date_indexes = {label: index for index, label in enumerate(daily_labels)}
        category_totals = {
            category.pk: {
                'category_id': category.pk,
                'label': category.name,
                'data': [0.0] * len(daily_labels),
            }
            for category in all_expense_categories
        }
        if any(row['category_id'] is None for row in daily_totals):
            category_totals['uncategorized'] = {
                'category_id': 'uncategorized',
                'label': 'Uncategorized',
                'data': [0.0] * len(daily_labels),
            }
        for row in daily_totals:
            category_key = row['category_id'] if row['category_id'] is not None else 'uncategorized'
            category_totals[category_key]['data'][date_indexes[row['date'].isoformat()]] = float(row['total'])
        daily_datasets = list(category_totals.values())
        if category_id:
            daily_datasets = [
                dataset for dataset in daily_datasets
                if str(dataset['category_id']) == category_id
            ]

    analysis_date = parse_date(request.GET.get('analysis_date', '')) if request.GET.get('analysis_date') else None
    if request.GET.get('analysis_date') and not analysis_date:
        return JsonResponse({'error': 'analysis_date must be a valid date.'}, status=400)
    if analysis_date is None and daily_labels:
        analysis_date = parse_date(daily_labels[-1])

    day_analysis = None
    if analysis_date:
        analysis_transactions = Transaction.objects.filter(
            user=request.user,
            transaction_type=Transaction.TransactionType.EXPENSE,
            date=analysis_date,
        ).filter(
            Q(category__in=all_expense_categories) | Q(category__isnull=True)
        ).select_related('category').order_by('category__name', 'id')
        transaction_rows = [
            {
                'id': transaction.pk,
                'category_id': transaction.category_id or 'uncategorized',
                'category': transaction.category.name if transaction.category_id else (
                    transaction.merchant or 'Uncategorized'
                ),
                'amount': transaction.amount,
            }
            for transaction in analysis_transactions
        ]
        category_amounts = {
            category.pk: {
                'category_id': category.pk,
                'name': category.name,
                'amount': Decimal('0.00'),
            }
            for category in all_expense_categories
        }
        if any(transaction.category_id is None for transaction in analysis_transactions):
            category_amounts['uncategorized'] = {
                'category_id': 'uncategorized',
                'name': 'Uncategorized',
                'amount': Decimal('0.00'),
            }
        for transaction in transaction_rows:
            category_amounts[transaction['category_id']]['amount'] += transaction['amount']
        day_total = sum(
            (category['amount'] for category in category_amounts.values()),
            Decimal('0.00'),
        )
        day_analysis = {
            'date': analysis_date.isoformat(),
            'total': float(day_total),
            'categories': [
                {
                    'category_id': category['category_id'],
                    'name': category['name'],
                    'amount': float(category['amount']),
                    'percentage': round(float(category['amount'] / day_total * 100), 1) if day_total else 0,
                }
                for category in category_amounts.values()
            ],
            'transactions': [
                {**transaction, 'amount': float(transaction['amount'])}
                for transaction in transaction_rows
            ],
        }

    return JsonResponse({
        "daily": {
            "labels": [entry['day'].strftime('%d %b') for entry in daily_qs if entry['day']],
            "data": [float(entry['total']) for entry in daily_qs]
        },
        "daily_by_category": {
            "labels": daily_labels,
            "datasets": daily_datasets,
        },
        "day_analysis": day_analysis,
        "expense_categories": [
            {'id': category.pk, 'name': category.name}
            for category in all_expense_categories
        ],
        "monthly": {
            "labels": [entry['month'].strftime('%B %Y') for entry in monthly_qs if entry['month']],
            "data": [float(entry['total']) for entry in monthly_qs]
        }
    })


@login_required
def monthly_income_savings_api(request):
    today = timezone.localdate()
    current_month_index = today.year * 12 + today.month - 1
    month_starts = []
    labels = []
    month_keys = []

    for offset in range(5, -1, -1):
        year, month_index = divmod(current_month_index - offset, 12)
        month = month_index + 1
        month_start = today.replace(year=year, month=month, day=1)
        month_starts.append(month_start)
        month_keys.append((year, month))
        labels.append(month_start.strftime('%b %Y'))

    income_totals = {
        (row['date__year'], row['date__month']): row['total']
        for row in Transaction.objects.filter(
            user=request.user,
            transaction_type=Transaction.TransactionType.INCOME,
            date__gte=month_starts[0],
            date__lte=today,
        ).values('date__year', 'date__month').annotate(total=Sum('amount'))
    }
    savings_totals = {
        (row['date__year'], row['date__month']): row['total']
        for row in SavingsTransaction.objects.filter(
            user=request.user,
            date__gte=month_starts[0],
            date__lte=today,
        ).values('date__year', 'date__month').annotate(total=Sum('amount'))
    }

    monthly_income = [float(income_totals.get(key, 0)) for key in month_keys]
    monthly_saved = [float(savings_totals.get(key, 0)) for key in month_keys]
    current_income = monthly_income[-1]
    current_saved = monthly_saved[-1]
    previous_saved = monthly_saved[-2]

    return JsonResponse({
        'labels': labels,
        'monthly_income': monthly_income,
        'monthly_saved': monthly_saved,
        'current_month_income': current_income,
        'current_month_saved': current_saved,
        'previous_month_saved': previous_saved,
        'previous_month_label': labels[-2],
        'savings_change': current_saved - previous_saved,
        'current_month_savings_rate': round(current_saved / current_income * 100, 1)
        if current_income > 0 else None,
    })
