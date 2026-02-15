from django.shortcuts import   redirect,render
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.db.models import Sum
from .models import Transaction
from .forms import TransactionForm
from datetime import datetime
from .models import Budget
from .models import SavingsGoal
import json

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

        transactions = Transaction.objects.filter(user=request.user)
        recent_transactions = transactions.order_by('-date')[:5]



        total_income = transactions.filter(
            category__category_type='income'
        ).aggregate(Sum('amount'))['amount__sum'] or 0

        total_expense = transactions.filter(
            category__category_type='expense'
        ).aggregate(Sum('amount'))['amount__sum'] or 0

        balance = total_income - total_expense

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
            elif total_expense > (budget.monthly_limit * 0.8):
                budget_warning = "⚠ Warning: You are close to your budget limit."
            # Expense category breakdown for pie chart
        expense_categories = transactions.filter(
            category__category_type='expense'
        ).values('category__name').annotate(total=Sum('amount'))

        goals = SavingsGoal.objects.filter(user=request.user)

        labels = [item['category__name'] for item in expense_categories]
        data = [float(item['total']) for item in expense_categories]

        print(labels)
        print(data)

        context = {
    'total_income': total_income,
    'total_expense': total_expense,
    'balance': balance,
    'labels': json.dumps(labels),
    'data': json.dumps(data),
    'budget_warning': budget_warning,
    'goals': goals,
    'recent_transactions': recent_transactions,

}



        return render(request, 'dashboard.html', context)



@login_required
def add_transaction(request):
    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.user = request.user
            transaction.save()
            return redirect('dashboard')
    else:
        form = TransactionForm()

    return render(request, 'add_transaction.html', {'form': form})

@login_required
def edit_transaction(request, pk):
    transaction = Transaction.objects.get(pk=pk, user=request.user)

    if request.method == 'POST':
        form = TransactionForm(request.POST, instance=transaction)
        if form.is_valid():
            form.save()
            return redirect('dashboard')
    else:
        form = TransactionForm(instance=transaction)

    return render(request, 'add_transaction.html', {'form': form})

@login_required
def delete_transaction(request, pk):
    transaction = Transaction.objects.get(pk=pk, user=request.user)
    transaction.delete()
    return redirect('dashboard')


