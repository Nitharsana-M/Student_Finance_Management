from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class Category(models.Model):
    CATEGORY_TYPE = (
        ('income', 'Income'),
        ('expense', 'Expense'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    category_type = models.CharField(max_length=10, choices=CATEGORY_TYPE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (('user', 'name'),)
        ordering = ('name', 'id')

    def __str__(self):
        return self.name


class Transaction(models.Model):
    class TransactionType(models.TextChoices):
        INCOME = 'income', 'Income'
        EXPENSE = 'expense', 'Expense'
        SAVINGS = 'savings', 'Savings'

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    merchant = models.CharField(max_length=255, default='General')
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    transaction_type = models.CharField(
        max_length=10,
        choices=TransactionType.choices,
        default=TransactionType.EXPENSE,
    )
    date = models.DateField(default=timezone.now)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at', '-id')

    def save(self, *args, **kwargs):
        if self.category_id and self.transaction_type != self.TransactionType.SAVINGS:
            category_type = Category.objects.filter(
                pk=self.category_id,
                user_id=self.user_id,
            ).values_list('category_type', flat=True).first()
            if category_type:
                self.transaction_type = category_type
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.get_transaction_type_display()} — {self.merchant}: {self.amount}'


class SavingsGoal(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    target_amount = models.DecimalField(max_digits=10, decimal_places=2)
    deadline = models.DateField()
    is_completed = models.BooleanField(default=False)

    @property
    def saved_amount(self):
        return self.transactions.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

    @property
    def progress_percentage(self):
        if self.target_amount <= 0:
            return 0
        return float(self.saved_amount / self.target_amount) * 100

    def __str__(self):
        return self.title


class Budget(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    monthly_limit = models.DecimalField(max_digits=10, decimal_places=2)
    month = models.IntegerField()
    year = models.IntegerField()
    planned_income = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    allocated_expenses = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    allocated_savings = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )

    @property
    def unallocated_balance(self):
        return self.planned_income - self.allocated_expenses - self.allocated_savings

    @property
    def is_zero_based(self):
        return self.unallocated_balance == Decimal('0.00')

    def __str__(self):
        return f'{self.user.username} — {self.year}-{self.month:02d} budget'


class SavingsTransaction(models.Model):
    goal = models.ForeignKey(SavingsGoal, on_delete=models.CASCADE, related_name='transactions')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(auto_now_add=True)

    def __str__(self):
        return f'{self.goal.title} - {self.amount}'


class FinancialStreak(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='financial_streak')
    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    fire_badge_count = models.PositiveIntegerField(default=0)
    last_activity_date = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user.username} — {self.current_streak} month streak'
