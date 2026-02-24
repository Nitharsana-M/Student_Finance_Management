from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.db.models import Sum
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import Transaction, Budget, SavingsGoal, SavingsTransaction
from .forms import TransactionForm, SavingsGoalForm, SavingsTransactionForm, UserProfileForm
from datetime import datetime
from decimal import Decimal
import json
from datetime import timedelta
from django.utils import timezone
from django.db.models.functions import TruncDay, TruncMonth


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
    return render(request, 'dashboard.html')

@login_required
def transactions_view(request):
    return render(request, 'transactions.html')

@login_required
def goals_view(request):
    return render(request, 'goals.html')


# ─── AJAX: Summary data ────────────────────────────────────────────────
@login_required
def api_summary(request):
    transactions = Transaction.objects.filter(user=request.user)

    total_income = transactions.filter(
        category__category_type='income'
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    total_expense = transactions.filter(
        category__category_type='expense'
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
        category__category_type='expense'
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
    transactions = Transaction.objects.filter(user=request.user).order_by('-date')[:20]
    result = []
    for t in transactions:
        result.append({
            'id': t.pk,
            'date': str(t.date),
            'category': t.category.name,
            'category_type': t.category.category_type,
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
            for st in g.transactions.all():
                history.append({'amount': float(st.amount), 'date': str(st.date)})
            saved = float(g.saved_amount)
            target = float(g.target_amount)
            progress = round((saved / target * 100) if target > 0 else 0, 1)
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
    today = timezone.now().date()
    
    if time_filter == 'last_7_days':
        start_date = today - timedelta(days=7)
    elif time_filter == 'last_6_months':
        # Approx 6 months
        start_date = today - timedelta(days=180)
    else:
        start_date = today - timedelta(days=30)
        
    base_qs = Transaction.objects.filter(
        user=request.user,
        category__category_type='expense',
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
    
    return JsonResponse({
        "daily": {
            "labels": [entry['day'].strftime('%d %b') for entry in daily_qs if entry['day']],
            "data": [float(entry['total']) for entry in daily_qs]
        },
        "monthly": {
            "labels": [entry['month'].strftime('%B %Y') for entry in monthly_qs if entry['month']],
            "data": [float(entry['total']) for entry in monthly_qs]
        }
    })
