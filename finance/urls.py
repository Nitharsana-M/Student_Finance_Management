from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Regular form pages
    path('add/', views.add_transaction, name='add_transaction'),
    path('edit/<int:pk>/', views.edit_transaction, name='edit_transaction'),
    path('delete/<int:pk>/', views.delete_transaction, name='delete_transaction'),
    path('delete-ajax/<int:pk>/', views.delete_transaction_ajax, name='delete_transaction_ajax'),
    path('add-goal/', views.add_goal, name='add_goal'),
    path('add-savings/<int:goal_id>/', views.add_savings, name='add_savings'),
    path('withdraw/<int:goal_id>/', views.withdraw_savings, name='withdraw_savings'),

    # Pages
    path('transactions/', views.transactions_view, name='transactions'),
    path('goals/', views.goals_view, name='goals'),

    # AJAX API endpoints
    path('api/summary/', views.api_summary, name='api_summary'),
    path('api/transactions/', views.api_transactions, name='api_transactions'),
    path('api/goals/', views.api_goals, name='api_goals'),
    path('api/progress/', views.api_progress, name='api_progress'),

    # Profile
    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),

     path('api/expenses/', views.expense_data_api, name='expense_data_api'),
]
