from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Category, Transaction, SavingsGoal, Budget

admin.site.register(Category)
admin.site.register(Transaction)
admin.site.register(SavingsGoal)
admin.site.register(Budget)
