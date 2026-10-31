from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from .models import Budget, Category, FinancialStreak, SavingsGoal, SavingsTransaction, Transaction


class FinanceHistoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='student', password='test-password')
        self.other_user = User.objects.create_user(username='other', password='test-password')
        self.client.force_login(self.user)
        self.category = Category.objects.create(
            user=self.user,
            name='Food',
            category_type='expense',
        )

    def test_api_transactions_returns_complete_history(self):
        Transaction.objects.bulk_create([
            Transaction(
                user=self.user,
                category=self.category,
                amount=Decimal('5.00'),
                date=date(2026, 1, index),
            )
            for index in range(1, 26)
        ])

        response = self.client.get(reverse('api_transactions'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['transactions']), 25)

    def test_api_transactions_can_limit_overview_results(self):
        Transaction.objects.bulk_create([
            Transaction(
                user=self.user,
                category=self.category,
                amount=Decimal('5.00'),
                date=date(2026, 1, index),
            )
            for index in range(1, 26)
        ])

        response = self.client.get(reverse('api_transactions'), {'limit': 5})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['transactions']), 5)

    def test_api_transactions_can_filter_income_for_editing(self):
        income_category = Category.objects.create(
            user=self.user,
            name='Part-time work',
            category_type='income',
        )
        Transaction.objects.create(
            user=self.user,
            category=self.category,
            amount=Decimal('15.00'),
            date=date(2026, 1, 1),
        )
        income = Transaction.objects.create(
            user=self.user,
            category=income_category,
            amount=Decimal('500.00'),
            date=date(2026, 1, 2),
        )

        response = self.client.get(reverse('api_transactions'), {'type': 'income'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['transactions']), 1)
        self.assertEqual(response.json()['transactions'][0]['id'], income.pk)
        self.assertEqual(response.json()['transactions'][0]['category_id'], income_category.pk)

    def test_api_transactions_rejects_unknown_type_filter(self):
        response = self.client.get(reverse('api_transactions'), {'type': 'savings'})

        self.assertEqual(response.status_code, 400)

    def test_dashboard_data_api_aggregates_user_totals_and_dynamic_categories(self):
        other_category = Category.objects.create(
            user=self.user,
            name='Other',
            category_type='expense',
        )
        private_category = Category.objects.create(
            user=self.other_user,
            name='Private label',
            category_type='expense',
        )
        income_category = Category.objects.create(
            user=self.user,
            name='Salary',
            category_type='income',
        )
        Transaction.objects.create(
            user=self.user,
            category=income_category,
            amount=Decimal('1500.00'),
            date=date(2026, 6, 1),
        )
        Transaction.objects.create(
            user=self.user,
            category=self.category,
            amount=Decimal('100.00'),
            date=date(2026, 6, 2),
        )
        Transaction.objects.create(
            user=self.user,
            category=other_category,
            amount=Decimal('25.00'),
            date=date(2026, 6, 3),
        )
        Transaction.objects.create(
            user=self.user,
            category=None,
            merchant='Unsorted purchase',
            amount=Decimal('10.00'),
            date=date(2026, 6, 4),
        )
        Transaction.objects.create(
            user=self.user,
            category=private_category,
            amount=Decimal('7.00'),
            date=date(2026, 6, 5),
        )
        Transaction.objects.create(
            user=self.other_user,
            category=None,
            amount=Decimal('900.00'),
            date=date(2026, 6, 4),
        )

        response = self.client.get(reverse('api_dashboard_data'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['total_income'], 1500.0)
        self.assertEqual(data['total_expense'], 142.0)
        self.assertEqual(data['net_savings'], 1358.0)
        self.assertEqual(data['tx_count'], 5)
        self.assertEqual(
            dict(zip(data['labels'], data['data'])),
            {'Food': 100.0, 'Other': 42.0},
        )
        self.assertEqual(len(data['recent_transactions']), 5)
        self.assertEqual(data['recent_transactions'][0]['category'], 'Other')

    def test_dashboard_data_api_limits_recent_transactions_to_ten(self):
        Transaction.objects.bulk_create([
            Transaction(
                user=self.user,
                category=self.category,
                amount=Decimal('1.00'),
                date=date(2026, 6, index),
            )
            for index in range(1, 13)
        ])

        response = self.client.get(reverse('api_dashboard_data'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['tx_count'], 12)
        self.assertEqual(len(data['recent_transactions']), 10)
        self.assertEqual(data['recent_transactions'][0]['date'], '2026-06-12')

    def test_dashboard_view_renders_dynamic_dashboard_data(self):
        Transaction.objects.create(
            user=self.user,
            category=self.category,
            amount=Decimal('45.00'),
            date=date(2026, 6, 1),
        )

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '"labels": ["Food"]')
        self.assertContains(response, '"tx_count": 1')

    def test_transaction_defaults_and_category_type_are_kept_in_sync(self):
        income_category = Category.objects.create(
            user=self.user,
            name='Part-time work',
            category_type='income',
        )

        transaction = Transaction.objects.create(
            user=self.user,
            category=income_category,
            amount=Decimal('500.00'),
        )

        self.assertEqual(transaction.transaction_type, Transaction.TransactionType.INCOME)
        self.assertEqual(transaction.merchant, 'General')
        self.assertIsNotNone(transaction.date)

    def test_uncategorized_transaction_remains_available_in_history(self):
        transaction = Transaction.objects.create(
            user=self.user,
            category=None,
            merchant='Corner shop',
            amount=Decimal('25.00'),
        )

        response = self.client.get(reverse('api_transactions'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['transactions'][0]['id'], transaction.pk)
        self.assertEqual(response.json()['transactions'][0]['category'], 'Corner shop')

    def test_budget_reports_zero_based_allocations(self):
        budget = Budget.objects.create(
            user=self.user,
            month=6,
            year=2026,
            monthly_limit=Decimal('1000.00'),
            planned_income=Decimal('3000.00'),
            allocated_expenses=Decimal('2000.00'),
            allocated_savings=Decimal('1000.00'),
        )

        self.assertEqual(budget.unallocated_balance, Decimal('0.00'))
        self.assertTrue(budget.is_zero_based)

        budget.allocated_expenses = Decimal('1999.99')
        self.assertFalse(budget.is_zero_based)

    def test_savings_goal_progress_is_derived_from_transaction_history(self):
        goal = SavingsGoal.objects.create(
            user=self.user,
            title='Laptop',
            target_amount=Decimal('1000.00'),
            deadline=date(2026, 12, 31),
        )
        SavingsTransaction.objects.create(
            goal=goal,
            user=self.user,
            amount=Decimal('250.00'),
        )

        self.assertEqual(goal.saved_amount, Decimal('250.00'))
        self.assertEqual(goal.progress_percentage, 25.0)

    def test_financial_streak_is_user_scoped(self):
        streak = FinancialStreak.objects.create(
            user=self.user,
            current_streak=3,
            longest_streak=5,
            fire_badge_count=1,
        )

        self.assertEqual(streak.user, self.user)
        self.assertEqual(FinancialStreak.objects.count(), 1)

    def test_income_transaction_can_be_updated(self):
        income_category = Category.objects.create(
            user=self.user,
            name='Part-time work',
            category_type='income',
        )
        transaction = Transaction.objects.create(
            user=self.user,
            category=income_category,
            amount=Decimal('500.00'),
            date=date(2026, 1, 2),
        )

        response = self.client.post(
            reverse('edit_transaction', args=[transaction.pk]),
            {
                'category': income_category.pk,
                'amount': '750.00',
                'date': '2026-01-15',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        transaction.refresh_from_db()
        self.assertEqual(transaction.amount, Decimal('750.00'))
        self.assertEqual(transaction.date, date(2026, 1, 15))

    def test_goal_delete_removes_goal_and_contribution_history(self):
        goal = SavingsGoal.objects.create(
            user=self.user,
            title='Laptop',
            target_amount=Decimal('1000.00'),
            deadline=date(2026, 12, 31),
        )
        history = SavingsTransaction.objects.create(
            goal=goal,
            user=self.user,
            amount=Decimal('25.00'),
        )

        response = self.client.post(reverse('delete_goal', args=[goal.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'success': True})
        self.assertFalse(SavingsGoal.objects.filter(pk=goal.pk).exists())
        self.assertFalse(SavingsTransaction.objects.filter(pk=history.pk).exists())

    def test_goal_delete_does_not_allow_deleting_another_users_goal(self):
        goal = SavingsGoal.objects.create(
            user=self.other_user,
            title='Private goal',
            target_amount=Decimal('100.00'),
            deadline=date(2026, 12, 31),
        )

        response = self.client.post(reverse('delete_goal', args=[goal.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(SavingsGoal.objects.filter(pk=goal.pk).exists())

    def test_goal_delete_requires_post(self):
        goal = SavingsGoal.objects.create(
            user=self.user,
            title='Laptop',
            target_amount=Decimal('1000.00'),
            deadline=date(2026, 12, 31),
        )

        response = self.client.get(reverse('delete_goal', args=[goal.pk]))

        self.assertEqual(response.status_code, 405)
        self.assertTrue(SavingsGoal.objects.filter(pk=goal.pk).exists())

    @patch('finance.views.timezone.localdate', return_value=date(2026, 6, 15))
    def test_monthly_income_savings_api_compares_monthly_income_and_net_savings(self, _today):
        income_category = Category.objects.create(
            user=self.user,
            name='Part-time work',
            category_type='income',
        )
        Transaction.objects.create(
            user=self.user,
            category=income_category,
            amount=Decimal('1200.00'),
            date=date(2026, 6, 5),
        )
        goal = SavingsGoal.objects.create(
            user=self.user,
            title='Laptop',
            target_amount=Decimal('1000.00'),
            deadline=date(2026, 12, 31),
        )
        saved = SavingsTransaction.objects.create(
            goal=goal,
            user=self.user,
            amount=Decimal('300.00'),
        )
        SavingsTransaction.objects.filter(pk=saved.pk).update(date=date(2026, 6, 7))
        withdrawn = SavingsTransaction.objects.create(
            goal=goal,
            user=self.user,
            amount=Decimal('-50.00'),
        )
        SavingsTransaction.objects.filter(pk=withdrawn.pk).update(date=date(2026, 6, 8))
        previous_month_saved = SavingsTransaction.objects.create(
            goal=goal,
            user=self.user,
            amount=Decimal('400.00'),
        )
        SavingsTransaction.objects.filter(pk=previous_month_saved.pk).update(date=date(2026, 5, 8))

        response = self.client.get(reverse('monthly_income_savings_api'))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['labels'][-1], 'Jun 2026')
        self.assertEqual(data['monthly_income'][-1], 1200.0)
        self.assertEqual(data['monthly_saved'][-1], 250.0)
        self.assertEqual(data['current_month_saved'], 250.0)
        self.assertEqual(data['previous_month_saved'], 400.0)
        self.assertEqual(data['previous_month_label'], 'May 2026')
        self.assertEqual(data['savings_change'], -150.0)
        self.assertEqual(data['current_month_savings_rate'], 20.8)
        self.assertEqual(data['monthly_income'][:-1], [0.0] * 5)

    @patch('finance.views.timezone.localdate', return_value=date(2026, 6, 15))
    def test_monthly_income_savings_api_only_counts_current_users_data(self, _today):
        other_category = Category.objects.create(
            user=self.other_user,
            name='Salary',
            category_type='income',
        )
        Transaction.objects.create(
            user=self.other_user,
            category=other_category,
            amount=Decimal('900.00'),
            date=date(2026, 6, 5),
        )

        response = self.client.get(reverse('monthly_income_savings_api'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['monthly_income'][-1], 0.0)
        self.assertIsNone(response.json()['current_month_savings_rate'])

    @patch('finance.views.timezone.localdate', return_value=date(2026, 3, 10))
    def test_expense_api_returns_daily_category_datasets(self, _today):
        travel = Category.objects.create(
            user=self.user,
            name='Travel',
            category_type='expense',
        )
        Transaction.objects.create(
            user=self.user,
            category=self.category,
            amount=Decimal('12.50'),
            date=date(2026, 3, 2),
        )
        Transaction.objects.create(
            user=self.user,
            category=travel,
            amount=Decimal('20.00'),
            date=date(2026, 3, 2),
        )
        Transaction.objects.create(
            user=self.user,
            category=self.category,
            amount=Decimal('7.00'),
            date=date(2026, 3, 5),
        )

        response = self.client.get(
            reverse('expense_data_api'),
            {'daily_filter': 'custom', 'start_date': '2026-03-01', 'end_date': '2026-03-08'},
        )

        self.assertEqual(response.status_code, 200)
        daily = response.json()['daily_by_category']
        self.assertEqual(daily['labels'], ['2026-03-02', '2026-03-05'])
        self.assertEqual(
            {dataset['label']: dataset['data'] for dataset in daily['datasets']},
            {'Food': [12.5, 7.0], 'Travel': [20.0, 0.0]},
        )

    @patch('finance.views.timezone.localdate', return_value=date(2026, 3, 10))
    def test_expense_api_can_filter_daily_data_by_category(self, _today):
        travel = Category.objects.create(
            user=self.user,
            name='Travel',
            category_type='expense',
        )
        Transaction.objects.create(
            user=self.user,
            category=self.category,
            amount=Decimal('12.50'),
            date=date(2026, 3, 2),
        )
        Transaction.objects.create(
            user=self.user,
            category=travel,
            amount=Decimal('20.00'),
            date=date(2026, 3, 2),
        )
        Transaction.objects.create(
            user=self.user,
            category=travel,
            amount=Decimal('5.00'),
            date=date(2026, 3, 4),
        )

        response = self.client.get(
            reverse('expense_data_api'),
            {'daily_filter': 'this_month', 'category': self.category.pk},
        )

        self.assertEqual(response.status_code, 200)
        daily = response.json()['daily_by_category']
        self.assertEqual(daily['labels'], ['2026-03-02', '2026-03-04'])
        self.assertEqual(len(daily['datasets']), 1)
        self.assertEqual(daily['datasets'][0]['label'], 'Food')
        self.assertEqual(daily['datasets'][0]['data'], [12.5, 0.0])

    @patch('finance.views.timezone.localdate', return_value=date(2026, 3, 10))
    def test_expense_api_includes_uncategorized_expenses_in_daily_analysis(self, _today):
        Transaction.objects.create(
            user=self.user,
            category=None,
            merchant='Corner shop',
            amount=Decimal('8.00'),
            date=date(2026, 3, 4),
        )

        response = self.client.get(
            reverse('expense_data_api'),
            {'daily_filter': 'this_month', 'category': 'uncategorized'},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['daily_by_category']['labels'], ['2026-03-04'])
        self.assertEqual(data['daily_by_category']['datasets'][0]['label'], 'Uncategorized')
        self.assertEqual(data['daily_by_category']['datasets'][0]['data'], [8.0])
        self.assertEqual(data['day_analysis']['total'], 8.0)
        uncategorized = next(
            category for category in data['day_analysis']['categories']
            if category['name'] == 'Uncategorized'
        )
        self.assertEqual(uncategorized['amount'], 8.0)
        self.assertEqual(data['day_analysis']['transactions'][0]['category'], 'Corner shop')

    @patch('finance.views.timezone.localdate', return_value=date(2026, 3, 10))
    def test_expense_api_includes_all_categories_for_all_category_filter(self, _today):
        travel = Category.objects.create(
            user=self.user,
            name='Travel',
            category_type='expense',
        )
        books = Category.objects.create(
            user=self.user,
            name='Books',
            category_type='expense',
        )
        Transaction.objects.create(
            user=self.user,
            category=self.category,
            amount=Decimal('12.50'),
            date=date(2026, 3, 2),
        )
        Transaction.objects.create(
            user=self.user,
            category=travel,
            amount=Decimal('20.00'),
            date=date(2026, 3, 2),
        )

        response = self.client.get(
            reverse('expense_data_api'),
            {'daily_filter': 'this_month'},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            {category['name'] for category in data['expense_categories']},
            {'Food', 'Travel', 'Books'},
        )
        daily = data['daily_by_category']
        self.assertEqual(
            {dataset['label']: dataset['data'] for dataset in daily['datasets']},
            {'Food': [12.5], 'Travel': [20.0], 'Books': [0.0]},
        )

    def test_expense_api_rejects_invalid_custom_date_range(self):
        response = self.client.get(
            reverse('expense_data_api'),
            {'daily_filter': 'custom', 'start_date': '2026-03-09', 'end_date': '2026-03-01'},
        )

        self.assertEqual(response.status_code, 400)

    @patch('finance.views.timezone.localdate', return_value=date(2026, 3, 10))
    def test_expense_api_returns_daily_analysis_and_transactions(self, _today):
        travel = Category.objects.create(
            user=self.user,
            name='Travel',
            category_type='expense',
        )
        Transaction.objects.create(
            user=self.user,
            category=self.category,
            amount=Decimal('12.50'),
            date=date(2026, 3, 2),
        )
        Transaction.objects.create(
            user=self.user,
            category=travel,
            amount=Decimal('37.50'),
            date=date(2026, 3, 2),
        )

        response = self.client.get(
            reverse('expense_data_api'),
            {'daily_filter': 'this_month', 'analysis_date': '2026-03-02'},
        )

        self.assertEqual(response.status_code, 200)
        analysis = response.json()['day_analysis']
        self.assertEqual(analysis['date'], '2026-03-02')
        self.assertEqual(analysis['total'], 50.0)
        self.assertEqual(
            {category['name']: (category['amount'], category['percentage']) for category in analysis['categories']},
            {'Food': (12.5, 25.0), 'Travel': (37.5, 75.0)},
        )
        self.assertEqual(len(analysis['transactions']), 2)
