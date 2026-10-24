from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.http import JsonResponse
from .forms import CustomUserCreationForm

def register_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('health')
    else:
        form = CustomUserCreationForm()
    return render(request, 'auth/register.html', {'form': form})

def health_check(request):
    return JsonResponse({'status': 'ok', 'user': request.user.username if request.user.is_authenticated else 'anonymous'})